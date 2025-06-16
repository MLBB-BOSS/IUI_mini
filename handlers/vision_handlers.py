import base64
import html
import logging
import re
from typing import Dict, Any, Optional, Union
from decimal import Decimal, ROUND_HALF_UP # Додано для точного округлення

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

# Імпорти з проєкту
from config import OPENAI_API_KEY, logger
from services.openai_service import (
    MLBBChatGPT,
    PROFILE_SCREENSHOT_PROMPT,
    PLAYER_STATS_PROMPT
)
from states.vision_states import VisionAnalysisStates
from utils.message_utils import send_message_in_chunks


# === ДОПОМІЖНІ ФУНКЦІЇ ДЛЯ БЕЗПЕЧНОГО ОТРИМАННЯ ЧИСЕЛ ТА РОЗРАХУНКІВ ===
# Клас MLBBAnalyticsCalculator залишається тут, як у наданому тобою файлі.
# Я припускаю, що він вже містить необхідні методи для розрахунків.
# Якщо його немає у твоєму поточному файлі, його треба буде додати з попереднього прикладу.
# Для стислості, я не буду повторювати тут весь клас MLBBAnalyticsCalculator,
# але він повинен бути присутнім для роботи calculate_derived_stats.

class MLBBAnalyticsCalculator: # Скорочена версія для контексту, використовуй повну з попереднього файлу
    @staticmethod
    def safe_divide(numerator: Union[int, float, str], denominator: Union[int, float, str],
                   precision: int = 2) -> Optional[float]:
        try:
            num = float(str(numerator).replace(',', '').replace(' ', ''))
            den = float(str(denominator).replace(',', '').replace(' ', ''))
            if den == 0: return None
            result = num / den
            return float(Decimal(str(result)).quantize(Decimal(f'0.{"0"*precision}'), rounding=ROUND_HALF_UP))
        except: return None

    @staticmethod
    def safe_number(value: Any) -> Optional[float]:
        if value is None: return None
        try: return float(str(value).replace(',', '').replace(' ', ''))
        except: return None

    # ... (інші методи калькулятора, якщо вони використовуються в calculate_derived_stats)


def calculate_derived_stats(stats_data: Dict[str, Any]) -> Dict[str, Union[str, float, int, None]]:
    """
    Розраховує додаткові унікальні статистичні показники на основі даних від Vision API.
    """
    derived: Dict[str, Union[str, float, int, None]] = {}
    calc = MLBBAnalyticsCalculator() # Використовуємо клас калькулятора

    main_ind = stats_data.get("main_indicators", {})
    details_p = stats_data.get("details_panel", {})
    ach_left = stats_data.get("achievements_left_column", {})
    ach_right = stats_data.get("achievements_right_column", {})

    matches_played = calc.safe_number(main_ind.get('matches_played'))
    win_rate_percent = calc.safe_number(main_ind.get('win_rate'))
    mvp_count = calc.safe_number(main_ind.get('mvp_count'))
    
    savage_count = calc.safe_number(ach_right.get('savage_count'))
    legendary_count = calc.safe_number(ach_left.get('legendary_count'))
    mvp_loss_count = calc.safe_number(ach_right.get('mvp_loss_count'))
    
    kda_ratio = calc.safe_number(details_p.get('kda_ratio'))
    avg_deaths_per_match = calc.safe_number(details_p.get('avg_deaths_per_match'))
    avg_hero_dmg_per_min = calc.safe_number(details_p.get('avg_hero_dmg_per_min'))
    avg_gold_per_min = calc.safe_number(details_p.get('avg_gold_per_min'))

    if matches_played is not None and win_rate_percent is not None:
        total_wins = int(matches_played * (win_rate_percent / 100.0))
        derived['total_wins'] = total_wins
        derived['total_losses'] = int(matches_played - total_wins)
    else:
        derived['total_wins'], derived['total_losses'] = None, None

    if mvp_count is not None and matches_played is not None and matches_played > 0:
        derived['mvp_rate_percent'] = round((mvp_count / matches_played) * 100, 2)
    else: derived['mvp_rate_percent'] = None

    if savage_count is not None and matches_played is not None and matches_played > 0:
        derived['savage_frequency_per_1000_matches'] = round((savage_count / matches_played) * 1000, 2)
    else: derived['savage_frequency_per_1000_matches'] = None
        
    if legendary_count is not None and matches_played is not None and matches_played > 0:
        derived['legendary_frequency_per_100_matches'] = round((legendary_count / matches_played) * 100, 2)
    else: derived['legendary_frequency_per_100_matches'] = None

    if mvp_count is not None and mvp_count > 0 and mvp_loss_count is not None:
        mvp_wins = mvp_count - mvp_loss_count
        derived['mvp_win_share_percent'] = round((mvp_wins / mvp_count) * 100, 2) if mvp_wins >= 0 else 0.0
    else: derived['mvp_win_share_percent'] = None
        
    if avg_hero_dmg_per_min is not None and avg_gold_per_min is not None and avg_gold_per_min > 0:
        derived['damage_per_gold_ratio'] = round(avg_hero_dmg_per_min / avg_gold_per_min, 2)
    else: derived['damage_per_gold_ratio'] = None
        
    if kda_ratio is not None and avg_deaths_per_match is not None:
        if avg_deaths_per_match > 0:
            derived['avg_impact_score_per_match'] = round(kda_ratio * avg_deaths_per_match, 2)
        elif kda_ratio is not None:
             derived['avg_impact_score_per_match'] = round(kda_ratio, 2)
        else: derived['avg_impact_score_per_match'] = None
    else: derived['avg_impact_score_per_match'] = None
        
    logger.info(f"Розраховано унікальні статистики: {derived}")
    return derived

# === ОБРОБНИКИ КОМАНД ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===
# ... (cmd_analyze_profile, cmd_analyze_player_stats, handle_profile_screenshot залишаються без змін) ...
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzeprofile викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user; user_name_escaped = html.escape(user.first_name); user_id = user.id
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzeprofile.")
    await state.update_data(analysis_type="profile", vision_prompt=PROFILE_SCREENSHOT_PROMPT, original_user_name=user_name_escaped)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nБудь ласка, надішли мені скріншот свого профілю з Mobile Legends для аналізу.\nЯкщо передумаєш, просто надішли команду /cancel.")

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzestats викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user; user_name_escaped = html.escape(user.first_name); user_id = user.id
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzestats.")
    await state.update_data(analysis_type="player_stats", vision_prompt=PLAYER_STATS_PROMPT, original_user_name=user_name_escaped)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nБудь ласка, надішли мені скріншот своєї ігрової статистики (зазвичай розділ \"Statistics\" -> \"All Seasons\" або \"Current Season\").\nЯкщо передумаєш, просто надішли команду /cancel.")

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not message.chat: logger.error("handle_profile_screenshot: відсутній message.from_user або message.chat"); return
    user_data_state = await state.get_data()
    user_name_escaped = user_data_state.get("original_user_name", html.escape(message.from_user.first_name if message.from_user else "Гравець"))
    user_id = message.from_user.id; chat_id = message.chat.id
    logger.info(f"Отримано скріншот для аналізу від {user_name_escaped} (ID: {user_id}).")
    if not message.photo: await message.answer(f"Щось пішло не так, {user_name_escaped}. Будь ласка, надішли саме фото (скріншот)."); return
    photo_file_id = message.photo[-1].file_id
    try: await message.delete(); logger.info(f"Повідомлення користувача {user_name_escaped} (ID: {user_id}) зі скріншотом видалено.")
    except TelegramAPIError as e: logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped} (ID: {user_id}) зі скріншотом: {e}")
    await state.update_data(vision_photo_file_id=photo_file_id)
    caption_text = "Скріншот отримано.\nНатисніть «🔍 Аналіз», щоб дізнатися більше, або «🗑️ Видалити», щоб скасувати."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis"), InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")]])
    try:
        sent_message = await bot.send_photo(chat_id=chat_id, photo=photo_file_id, caption=caption_text, reply_markup=keyboard)
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
        logger.info(f"Скріншот від {user_name_escaped} (ID: {user_id}) повторно надіслано ботом з кнопками. Новий state: awaiting_analysis_trigger")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для аналізу для {user_name_escaped} (ID: {user_id}): {e}")
        try: await bot.send_message(chat_id, f"Не вдалося обробити ваш запит на аналіз, {user_name_escaped}. Спробуйте ще раз.")
        except TelegramAPIError as send_err: logger.error(f"Не вдалося надіслати повідомлення про помилку обробки аналізу для {user_name_escaped} (ID: {user_id}): {send_err}")
        await state.clear()


# === ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ АНАЛІЗУ ===

def format_profile_raw_data_for_pre_block(user_name: str, data: Dict[str, Any]) -> str:
    """Форматує 'сухі' дані профілю у простий текст для <pre> блоку."""
    if not data: return f"Не вдалося розпізнати дані профілю для {user_name}."
    
    lines = [f"Детальна інформація профілю гравця {user_name}:"]
    fields_translation = {
        "game_nickname": "Нікнейм", "mlbb_id_server": "ID (Сервер)",
        "highest_rank_season": "Найвищий ранг (сезон)",
        "matches_played": "Матчів зіграно", "likes_received": "Лайків отримано",
        "location": "Локація", "squad_name": "Сквад"
    }
    def _get_val_plain(source_dict, key, default="не розпізнано"):
        val = source_dict.get(key)
        return str(val) if val is not None else default

    for key, readable_name in fields_translation.items():
        value = _get_val_plain(data, key)
        lines.append(f"  • {readable_name}: {value}")
    return "\n".join(lines)

def format_derived_stats_for_html(derived_data: Dict[str, Any], stats_type: str = "player") -> str:
    """Форматує розраховані унікальні статистики у HTML для відображення."""
    if not derived_data: return ""
    
    parts = []
    def _format_val(val, suffix="", precision=2):
        if val is None: return "N/A"
        try: return f"{float(val):.{precision}f}{suffix}"
        except (ValueError, TypeError): return f"{html.escape(str(val))}{suffix}"

    # Спільні для профілю та статистики гравця (якщо будуть)
    if derived_data.get('total_wins') is not None and stats_type == "player":
        parts.append(f"  👑 Перемог/Поразок: <b>{derived_data['total_wins']} / {derived_data.get('total_losses', 'N/A')}</b>")
    if derived_data.get('mvp_rate_percent') is not None and stats_type == "player":
        parts.append(f"  ⭐ MVP Рейтинг: <b>{_format_val(derived_data['mvp_rate_percent'], '%')}</b> матчів")
    if derived_data.get('mvp_win_share_percent') is not None and stats_type == "player":
        parts.append(f"  🏆 Частка MVP у перемогах: <b>{_format_val(derived_data['mvp_win_share_percent'], '%')}</b>")
    if derived_data.get('savage_frequency_per_1000_matches') is not None and stats_type == "player":
        parts.append(f"  🔥 Частота Savage: ~<b>{_format_val(derived_data['savage_frequency_per_1000_matches'])}</b> на 1000 матчів")
    if derived_data.get('legendary_frequency_per_100_matches') is not None and stats_type == "player":
        parts.append(f"  ✨ Частота Legendary: ~<b>{_format_val(derived_data['legendary_frequency_per_100_matches'])}</b> на 100 матчів")
    if derived_data.get('damage_per_gold_ratio') is not None and stats_type == "player":
        parts.append(f"  ⚔️ Ефективність золота: <b>{_format_val(derived_data['damage_per_gold_ratio'])}</b> шкоди/хв на 1 золото/хв")
    if derived_data.get('avg_impact_score_per_match') is not None and stats_type == "player":
        parts.append(f"  🎯 Сер. Вплив (K+A)/матч: ~<b>{_format_val(derived_data['avg_impact_score_per_match'])}</b>")
    
    # Тут можна додати унікальну аналітику специфічну для профілю, якщо буде потрібно
    # Наприклад, аналіз активності на основі кількості матчів, якщо 'matches_played' є в derived_data для профілю

    return "\n".join(parts) if parts else "<i>Унікальна аналітика наразі недоступна.</i>"


def format_player_raw_stats_for_plain_text_pre_block(user_name: str, data: Dict[str, Any]) -> str:
    """Форматує 'сухі' дані статистики гравця у простий текст для <pre> блоку."""
    if not data: return f"Не вдалося розпізнати дані статистики для {user_name}."
    
    lines = [f"Детальна статистика гравця {user_name} ({data.get('stats_filter_type', 'N/A')}):"]
    
    def _get_val_plain(source_dict, key, default="N/A"):
        val = source_dict.get(key)
        return str(val) if val is not None else default

    main_ind = data.get("main_indicators", {})
    lines.append("\nОсновні показники:")
    lines.append(f"  • Матчів зіграно: {_get_val_plain(main_ind, 'matches_played')}")
    win_rate = _get_val_plain(main_ind, 'win_rate')
    lines.append(f"  • Відсоток перемог: {win_rate}%" if win_rate != "N/A" else "  • Відсоток перемог: N/A")
    lines.append(f"  • MVP: {_get_val_plain(main_ind, 'mvp_count')}")

    ach_left = data.get("achievements_left_column", {})
    lines.append("\nДосягнення (колонка 1):")
    lines.append(f"  • Легендарних: {_get_val_plain(ach_left, 'legendary_count')}")
    lines.append(f"  • Маніяків: {_get_val_plain(ach_left, 'maniac_count')}")
    lines.append(f"  • Подвійних вбивств: {_get_val_plain(ach_left, 'double_kill_count')}")
    lines.append(f"  • Найб. вбивств за гру: {_get_val_plain(ach_left, 'most_kills_in_one_game')}")
    lines.append(f"  • Найдовша серія перемог: {_get_val_plain(ach_left, 'longest_win_streak')}")
    lines.append(f"  • Найб. шкоди/хв: {_get_val_plain(ach_left, 'highest_dmg_per_min')}")
    lines.append(f"  • Найб. золота/хв: {_get_val_plain(ach_left, 'highest_gold_per_min')}")

    ach_right = data.get("achievements_right_column", {})
    lines.append("\nДосягнення (колонка 2):")
    lines.append(f"  • Дикунств (Savage): {_get_val_plain(ach_right, 'savage_count')}")
    lines.append(f"  • Потрійних вбивств: {_get_val_plain(ach_right, 'triple_kill_count')}")
    lines.append(f"  • MVP при поразці: {_get_val_plain(ach_right, 'mvp_loss_count')}")
    lines.append(f"  • Найб. допомоги за гру: {_get_val_plain(ach_right, 'most_assists_in_one_game')}")
    lines.append(f"  • Перша кров: {_get_val_plain(ach_right, 'first_blood_count')}")
    lines.append(f"  • Найб. отриманої шкоди/хв: {_get_val_plain(ach_right, 'highest_dmg_taken_per_min')}")

    details = data.get("details_panel", {})
    lines.append("\nДеталі (права панель):")
    lines.append(f"  • KDA: {_get_val_plain(details, 'kda_ratio')}")
    tf_part_rate = _get_val_plain(details, 'teamfight_participation_rate')
    lines.append(f"  • Участь у ком. боях: {tf_part_rate}%" if tf_part_rate != "N/A" else "  • Участь у ком. боях: N/A")
    lines.append(f"  • Сер. золото/хв: {_get_val_plain(details, 'avg_gold_per_min')}")
    lines.append(f"  • Сер. шкода героям/хв: {_get_val_plain(details, 'avg_hero_dmg_per_min')}")
    lines.append(f"  • Сер. смертей/матч: {_get_val_plain(details, 'avg_deaths_per_match')}")
    lines.append(f"  • Сер. шкода вежам/матч: {_get_val_plain(details, 'avg_turret_dmg_per_match')}")
    
    return "\n".join(lines)

# === ОБРОБКА КОЛБЕКІВ (НАТИСКАННЯ КНОПОК) ===
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True); await state.clear(); return

    chat_id = callback_query.message.chat.id; message_id = callback_query.message.message_id
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt"); analysis_type = user_data.get("analysis_type")

    if not photo_file_id or not vision_prompt or not analysis_type:
        logger.error(f"Недостатньо даних у стані для аналізу для {user_name} (ID: {callback_query.from_user.id}).")
        try:
            if callback_query.message and callback_query.message.caption: await callback_query.message.edit_caption(caption=f"Помилка, {user_name}: дані для аналізу втрачено або неповні. Спробуйте надіслати скріншот знову.")
            else: await bot.send_message(chat_id, f"Помилка, {user_name}: дані для аналізу втрачено або неповні. Спробуйте надіслати скріншот знову, викликавши відповідну команду.")
        except TelegramAPIError: pass
        await state.clear(); return

    try:
        if callback_query.message.caption: await callback_query.message.edit_caption(caption=f"⏳ Обробляю ваш скріншот, {user_name}...", reply_markup=None)
        else: await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e: logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name} (ID: {callback_query.from_user.id}): {e}")

    # Ініціалізація змінних для частин повідомлення
    gpt_comment_html = ""
    derived_stats_html = ""
    raw_stats_pre_block = ""
    error_message_text = f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."


    try:
        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path: raise ValueError("Не вдалося отримати шлях до файлу в Telegram.")
        downloaded_file_io = await bot.download_file(file_info.file_path)
        if downloaded_file_io is None: raise ValueError("Не вдалося завантажити файл з Telegram (download_file повернув None).")
        image_bytes = downloaded_file_io.read(); image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз ({analysis_type}) для {user_name} (ID: {callback_query.from_user.id}): {str(analysis_result_json)[:150]}...")
                
                data_for_description = analysis_result_json.copy()
                derived_stats_map: Optional[Dict[str, Any]] = None

                if analysis_type == "player_stats":
                    derived_stats_map = calculate_derived_stats(analysis_result_json)
                    if derived_stats_map:
                        data_for_description['derived_stats'] = derived_stats_map
                        derived_stats_html = format_derived_stats_for_html(derived_stats_map, stats_type="player")
                    raw_stats_pre_block = format_player_raw_stats_for_plain_text_pre_block(user_name, analysis_result_json)
                    
                    # Генерація коментаря для статистики
                    comment_text = await gpt_analyzer.get_player_stats_description(user_name, data_for_description)
                    if comment_text and "<i>" not in comment_text:
                        gpt_comment_html = f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(comment_text)}"
                    elif comment_text: # Якщо це заглушка/помилка, показуємо як є
                        gpt_comment_html = comment_text


                elif analysis_type == "profile":
                    # Для профілю, можливо, теж захочемо унікальну аналітику в майбутньому
                    # derived_stats_map = calculate_derived_stats_for_profile(analysis_result_json) # Приклад
                    # if derived_stats_map: derived_stats_html = format_derived_stats_for_html(derived_stats_map, stats_type="profile")
                    raw_stats_pre_block = format_profile_raw_data_for_pre_block(user_name, analysis_result_json)
                    
                    # Генерація коментаря для профілю
                    comment_text = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                    if comment_text and "<i>" not in comment_text:
                         gpt_comment_html = f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(comment_text)}"
                    elif comment_text:
                         gpt_comment_html = comment_text
                
                # Збираємо повідомлення в новому порядку
                final_parts = []
                if gpt_comment_html: final_parts.append(gpt_comment_html)
                if derived_stats_html: final_parts.append(f"<b>📈 <u>Унікальна Аналітика від IUI:</u></b>\n{derived_stats_html}")
                if raw_stats_pre_block:
                    header_text = "📊 <u>Детальна статистика профілю (для копіювання):</u>" if analysis_type == "profile" else "📊 <u>Детальна статистика гравця (для копіювання):</u>"
                    final_parts.append(f"{header_text}\n<pre>{html.escape(raw_stats_pre_block)}</pre>")
                
                final_caption_text = "\n\n".join(filter(None, final_parts)) if final_parts else error_message_text

            else: # Помилка від Vision API
                error_msg = analysis_result_json.get('error', 'Невідома помилка') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу ({analysis_type}) для {user_name}: {error_msg}. Деталі: {analysis_result_json.get('details') if analysis_result_json else 'N/A'}")
                final_caption_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
                raw_resp_snippet = (html.escape(str(analysis_result_json.get('raw_response'))[:150]) if analysis_result_json and analysis_result_json.get('raw_response') 
                                   else html.escape(str(analysis_result_json.get('details'))[:150]) if analysis_result_json and analysis_result_json.get('details') else "")
                if raw_resp_snippet: final_caption_text += f"\nДеталі: {raw_resp_snippet}..."
    
    except TelegramAPIError as e: logger.exception(f"Telegram API помилка під час обробки файлу для {user_name}: {e}"); final_caption_text = error_message_text
    except ValueError as e: logger.exception(f"Помилка значення під час обробки файлу для {user_name}: {e}"); final_caption_text = error_message_text
    except Exception as e: logger.exception(f"Критична помилка обробки скріншота ({analysis_type}) для {user_name}: {e}"); final_caption_text = error_message_text

    # Надсилання фінального повідомлення
    try:
        if callback_query.message:
            try: # Видаляємо кнопки, якщо вони ще є
                if callback_query.message.reply_markup: await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            except TelegramAPIError as e: logger.warning(f"Не вдалося видалити кнопки з повідомлення-прев'ю (ID: {message_id}) для {user_name}: {e}")

            # Надсилаємо результат
            if callback_query.message.photo and len(final_caption_text) <= 1024: # Ліміт підпису до фото
                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=final_caption_text, parse_mode=ParseMode.HTML)
            elif callback_query.message.photo and len(final_caption_text) > 1024:
                 logger.warning(f"Підпис до фото для {user_name} задовгий ({len(final_caption_text)}). Редагую фото без підпису, надсилаю текст окремо.")
                 await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption="✅ Аналіз завершено, деталі нижче:") # Короткий підпис
                 await send_message_in_chunks(bot, chat_id, final_caption_text, ParseMode.HTML)
            else: # Якщо це було не фото, або з якоїсь причини ми не редагуємо підпис
                logger.info(f"Надсилаю результат аналізу ({analysis_type}) для {user_name} окремим повідомленням.")
                await send_message_in_chunks(bot, chat_id, final_caption_text, ParseMode.HTML)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати/надіслати повідомлення з результатами аналізу ({analysis_type}) для {user_name}: {e}. Спроба надіслати як нове.")
        try: await send_message_in_chunks(bot, chat_id, final_caption_text, ParseMode.HTML)
        except Exception as send_err:
            logger.error(f"Не вдалося надіслати нове повідомлення з аналізом ({analysis_type}) для {user_name}: {send_err}")
            if callback_query.message:
                try: await bot.send_message(chat_id, f"Вибачте, {user_name}, сталася помилка при відображенні результатів аналізу. Спробуйте пізніше.")
                except Exception as final_fallback_err: logger.error(f"Не вдалося надіслати навіть текстове повідомлення про помилку аналізу для {user_name}: {final_fallback_err}")
    await state.clear()

# ... (решта файлу: delete_bot_message_callback, cancel_analysis, handle_wrong_input_for_analysis, register_vision_handlers - залишається без змін) ...
async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.message: logger.error("delete_bot_message_callback: callback_query.message is None."); await callback_query.answer("Помилка видалення.", show_alert=True); return
    try:
        await callback_query.message.delete(); await callback_query.answer("Повідомлення видалено.")
        current_state_str = await state.get_state()
        if current_state_str == VisionAnalysisStates.awaiting_analysis_trigger.state:
            user_data = await state.get_data(); user_name = user_data.get("original_user_name", f"Користувач (ID: {callback_query.from_user.id})")
            logger.info(f"Прев'ю аналізу видалено користувачем {user_name}. Стан очищено."); await state.clear()
        else: logger.info(f"Повідомлення бота видалено користувачем (ID: {callback_query.from_user.id}). Поточний стан: {current_state_str}")
    except TelegramAPIError as e: logger.error(f"Помилка видалення повідомлення бота для користувача (ID: {callback_query.from_user.id}): {e}"); await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)

async def cancel_analysis(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user: return
    user_name_escaped = html.escape(message.from_user.first_name)
    logger.info(f"Користувач {user_name_escaped} (ID: {message.from_user.id}) скасував аналіз зображення командою /cancel.")
    user_data = await state.get_data(); bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id and message.chat:
        try: await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id); logger.info(f"Видалено повідомлення-прев'ю бота (ID: {bot_message_id}) після скасування аналізу {user_name_escaped}.")
        except TelegramAPIError: logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота (ID: {bot_message_id}) при скасуванні для {user_name_escaped}.")
    await state.clear(); await message.reply(f"Аналіз зображення скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go або іншу команду аналізу.")

async def handle_wrong_input_for_analysis(message: Message, state: FSMContext, bot: Bot, cmd_go_handler_func) -> None:
    if not message.from_user: return
    user_name_escaped = html.escape(message.from_user.first_name); user_id = message.from_user.id
    if message.text and message.text.lower() == "/cancel": await cancel_analysis(message, state, bot); return
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data(); bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try: await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError: pass
        await state.clear(); await cmd_go_handler_func(message, state); return
    current_state_name = await state.get_state(); user_data = await state.get_data()
    analysis_type_display = user_data.get("analysis_type", "невідомого типу")
    if current_state_name == VisionAnalysisStates.awaiting_profile_screenshot.state:
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав не фото у стані awaiting_profile_screenshot (для аналізу типу: {analysis_type_display}).")
        await message.reply(f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) для аналізу {analysis_type_display} або команду /cancel для скасування.")
    elif current_state_name == VisionAnalysisStates.awaiting_analysis_trigger.state:
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав '{html.escape(message.text or 'не текстове повідомлення')}' у стані awaiting_analysis_trigger (для аналізу типу: {analysis_type_display}).")
        await message.reply(f"Очікувалася дія з аналізом (кнопка під фото) або команда /cancel, {user_name_escaped}.")
    else:
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав некоректне введення у непередбаченому стані аналізу ({current_state_name}). Пропоную скасувати.")
        await message.reply(f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.")

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None:
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    dp.message.register(cmd_analyze_player_stats, Command("analyzestats"))
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    dp.callback_query.register(trigger_vision_analysis_callback, F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
    dp.callback_query.register(delete_bot_message_callback, F.data == "delete_bot_message")
    cancel_states = [VisionAnalysisStates.awaiting_profile_screenshot, VisionAnalysisStates.awaiting_analysis_trigger]
    for cancel_state in cancel_states: dp.message.register(cancel_analysis, cancel_state, Command("cancel"))
    wrong_input_handler_with_go = lambda message, state, bot: handle_wrong_input_for_analysis(message, state, bot, cmd_go_handler_func)
    dp.message.register(wrong_input_handler_with_go, VisionAnalysisStates.awaiting_profile_screenshot)
    dp.message.register(wrong_input_handler_with_go, VisionAnalysisStates.awaiting_analysis_trigger)
    logger.info("Обробники аналізу зображень (профіль, статистика гравця) зареєстровано.")
