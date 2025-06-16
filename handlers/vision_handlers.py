import asyncio
import base64
import html
import logging 
import re
from typing import Dict, Any, Optional, Union

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
from utils.message_utils import send_message_in_chunks, MAX_TELEGRAM_MESSAGE_LENGTH 


# === ДОПОМІЖНА ФУНКЦІЯ ДЛЯ БЕЗПЕЧНОГО ОТРИМАННЯ ЧИСЕЛ ===
def _safe_get_float(data: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    if data is None: return None
    value = data.get(key)
    if value is None: return None
    try: return float(value)
    except (ValueError, TypeError):
        logger.debug(f"Не вдалося конвертувати '{value}' у float для ключа '{key}'")
        return None

def _safe_get_int(data: Optional[Dict[str, Any]], key: str) -> Optional[int]:
    if data is None: return None
    value = data.get(key)
    if value is None: return None
    try: return int(float(value))
    except (ValueError, TypeError):
        logger.debug(f"Не вдалося конвертувати '{value}' у int для ключа '{key}'")
        return None

# === РОЗРАХУНОК УНІКАЛЬНИХ СТАТИСТИК ===
def calculate_derived_stats(stats_data: Dict[str, Any]) -> Dict[str, Union[str, float, int, None]]:
    derived: Dict[str, Union[str, float, int, None]] = {}
    main_ind = stats_data.get("main_indicators", {})
    details_p = stats_data.get("details_panel", {})
    ach_left = stats_data.get("achievements_left_column", {})
    ach_right = stats_data.get("achievements_right_column", {})

    matches_played = _safe_get_int(main_ind, 'matches_played')
    win_rate_percent = _safe_get_float(main_ind, 'win_rate')
    mvp_count = _safe_get_int(main_ind, 'mvp_count')
    savage_count = _safe_get_int(ach_right, 'savage_count')
    legendary_count = _safe_get_int(ach_left, 'legendary_count')
    mvp_loss_count = _safe_get_int(ach_right, 'mvp_loss_count')
    kda_ratio = _safe_get_float(details_p, 'kda_ratio')
    avg_deaths_per_match = _safe_get_float(details_p, 'avg_deaths_per_match')
    avg_hero_dmg_per_min = _safe_get_float(details_p, 'avg_hero_dmg_per_min')
    avg_gold_per_min = _safe_get_float(details_p, 'avg_gold_per_min')

    if matches_played is not None and win_rate_percent is not None:
        total_wins = int(round(matches_played * (win_rate_percent / 100.0)))
        derived['total_wins'] = total_wins
        derived['total_losses'] = matches_played - total_wins
    else: derived.update({'total_wins': None, 'total_losses': None})

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
        if mvp_wins > 0: derived['mvp_win_share_percent'] = round((mvp_wins / mvp_count) * 100, 2)
        elif mvp_wins == 0: derived['mvp_win_share_percent'] = 0.0
        else: derived['mvp_win_share_percent'] = None 
    else: derived['mvp_win_share_percent'] = None
        
    if avg_hero_dmg_per_min is not None and avg_gold_per_min is not None and avg_gold_per_min > 0:
        derived['damage_per_gold_ratio'] = round(avg_hero_dmg_per_min / avg_gold_per_min, 2)
    else: derived['damage_per_gold_ratio'] = None
        
    if kda_ratio is not None and avg_deaths_per_match is not None:
        if avg_deaths_per_match > 0: derived['avg_impact_score_per_match'] = round(kda_ratio * avg_deaths_per_match, 2)
        elif kda_ratio is not None: derived['avg_impact_score_per_match'] = round(kda_ratio, 2)
        else: derived['avg_impact_score_per_match'] = None
    else: derived['avg_impact_score_per_match'] = None
        
    logger.info(f"Розраховано унікальні статистики: {derived}")
    return derived

# === ОБРОБНИКИ КОМАНД ===
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzeprofile викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    await state.update_data(
        analysis_type="profile",
        vision_prompt=PROFILE_SCREENSHOT_PROMPT,
        original_user_name=user.first_name
    )
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
        "Будь ласка, надішли мені скріншот свого профілю для аналізу.\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzestats викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    await state.update_data(
        analysis_type="player_stats",
        vision_prompt=PLAYER_STATS_PROMPT,
        original_user_name=user.first_name
    )
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
        "Будь ласка, надішли скріншот своєї ігрової статистики (розділ \"Statistics\" -> \"All Seasons\" або \"Current Season\").\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not message.chat:
        logger.error("handle_profile_screenshot: відсутній message.from_user або message.chat")
        return
    user_data_state = await state.get_data()
    user_name_original = user_data_state.get("original_user_name", message.from_user.first_name if message.from_user else "Гравець")
    user_name_escaped = html.escape(user_name_original)
    
    if not message.photo:
        await message.answer(f"Щось пішло не так, {user_name_escaped}. Будь ласка, надішли саме фото (скріншот).")
        return
    
    photo_file_id = message.photo[-1].file_id
    try: await message.delete()
    except TelegramAPIError as e: logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped}: {e}")
    
    await state.update_data(vision_photo_file_id=photo_file_id)
    caption_text = f"Скріншот отримано, {user_name_escaped}.\nНатисніть «🔍 Аналіз» або «🗑️ Видалити»."
    # Розділив кнопки на два рядки для кращого вигляду, якщо це доречно
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")],
        [InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")]
    ])
    
    try:
        sent_message = await bot.send_photo(message.chat.id, photo_file_id, caption=caption_text, reply_markup=keyboard)
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для {user_name_escaped}: {e}")
        try: await bot.send_message(message.chat.id, f"Не вдалося обробити запит, {user_name_escaped}. Спробуйте ще раз.")
        except TelegramAPIError as send_err: logger.error(f"Не вдалося надіслати повідомлення про помилку для {user_name_escaped}: {send_err}")
        await state.clear()

# === ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ ===
def format_profile_result(user_name: str, data: Dict[str, Any]) -> str:
    user_name_escaped = html.escape(user_name)
    if not data: return f"Не вдалося розпізнати дані профілю для {user_name_escaped}."
    parts = [f"<b>Детальний аналіз твого профілю, {user_name_escaped}:</b>"]
    fields_translation = {
        "game_nickname": "🎮 Нікнейм", "mlbb_id_server": "🆔 ID (Сервер)",
        "highest_rank_season": "🌟 Найвищий ранг (сезон)",
        "matches_played": "⚔️ Матчів зіграно", "likes_received": "👍 Лайків отримано",
        "location": "🌍 Локація", "squad_name": "🛡️ Сквад"
    }
    has_data = False
    for key, readable_name in fields_translation.items():
        value = data.get(key)
        if value is not None:
            display_value = str(value)
            if key == "highest_rank_season" and ("★" in display_value or "зірок" in display_value.lower() or "слава" in display_value.lower()):
                if "★" not in display_value: display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                display_value = re.sub(r'\s+★', '★', display_value)
            parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
            has_data = True
        else: parts.append(f"<b>{readable_name}:</b> <i>не розпізнано</i>")
    if not has_data and data.get("raw_response"):
        parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>")
    elif not has_data: parts.append(f"\n<i>Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")
    return "\n".join(parts)

def format_detailed_stats_text(user_name: str, data: Dict[str, Any]) -> str:
    user_name_escaped = html.escape(user_name)
    if not data: return f"Не вдалося розпізнати дані детальної статистики для {user_name_escaped}."
    parts = [f"<b>📊 Детальна статистика гравця {user_name_escaped} ({html.escape(str(data.get('stats_filter_type', 'N/A')))}):</b>"]
    main_ind = data.get("main_indicators", {})
    parts.append("\n<b><u>Основні показники:</u></b>")
    parts.append(f"  • Матчів зіграно: <b>{main_ind.get('matches_played', 'N/A')}</b>")
    win_rate = main_ind.get('win_rate')
    parts.append(f"  • Відсоток перемог: <b>{win_rate}%</b>" if win_rate is not None else "  • Відсоток перемог: N/A")
    parts.append(f"  • MVP: <b>{main_ind.get('mvp_count', 'N/A')}</b>")

    ach_left = data.get("achievements_left_column", {})
    parts.append("\n<b><u>Досягнення (колонка 1):</u></b>")
    parts.append(f"  • Легендарних: {ach_left.get('legendary_count', 'N/A')}")
    parts.append(f"  • Маніяків: {ach_left.get('maniac_count', 'N/A')}")
    parts.append(f"  • Подвійних вбивств: {ach_left.get('double_kill_count', 'N/A')}")
    parts.append(f"  • Найб. вбивств за гру: {ach_left.get('most_kills_in_one_game', 'N/A')}")
    parts.append(f"  • Найдовша серія перемог: {ach_left.get('longest_win_streak', 'N/A')}")
    parts.append(f"  • Найб. шкоди/хв: {ach_left.get('highest_dmg_per_min', 'N/A')}")
    parts.append(f"  • Найб. золота/хв: {ach_left.get('highest_gold_per_min', 'N/A')}")

    ach_right = data.get("achievements_right_column", {})
    parts.append("\n<b><u>Досягнення (колонка 2):</u></b>")
    parts.append(f"  • Дикунств (Savage): {ach_right.get('savage_count', 'N/A')}")
    parts.append(f"  • Потрійних вбивств: {ach_right.get('triple_kill_count', 'N/A')}")
    parts.append(f"  • MVP при поразці: {ach_right.get('mvp_loss_count', 'N/A')}")
    parts.append(f"  • Найб. допомоги за гру: {ach_right.get('most_assists_in_one_game', 'N/A')}")
    parts.append(f"  • Перша кров: {ach_right.get('first_blood_count', 'N/A')}")
    parts.append(f"  • Найб. отриманої шкоди/хв: {ach_right.get('highest_dmg_taken_per_min', 'N/A')}")

    details = data.get("details_panel", {})
    parts.append("\n<b><u>Деталі (права панель):</u></b>")
    parts.append(f"  • KDA: <b>{details.get('kda_ratio', 'N/A')}</b>")
    tf_rate = details.get('teamfight_participation_rate')
    parts.append(f"  • Участь у ком. боях: <b>{tf_rate}%</b>" if tf_rate is not None else "  • Участь у ком. боях: N/A")
    parts.append(f"  • Сер. золото/хв: {details.get('avg_gold_per_min', 'N/A')}")
    parts.append(f"  • Сер. шкода героям/хв: {details.get('avg_hero_dmg_per_min', 'N/A')}")
    parts.append(f"  • Сер. смертей/матч: {details.get('avg_deaths_per_match', 'N/A')}")
    parts.append(f"  • Сер. шкода вежам/матч: {details.get('avg_turret_dmg_per_match', 'N/A')}")
    return "\n".join(parts)

def format_unique_analytics_text(user_name: str, derived_data: Optional[Dict[str, Any]]) -> str:
    user_name_escaped = html.escape(user_name)
    if not derived_data: return f"Для гравця {user_name_escaped} недостатньо даних для розрахунку унікальної аналітики."
    parts = [f"<b>📈 <u>Унікальна Аналітика від IUI для {user_name_escaped}:</u></b>"]
    has_data = False
    def _format_derived_value(value: Any, precision: int = 2) -> str:
        if value is None: return "N/A"
        try: return f"{float(value):.{precision}f}"
        except (ValueError, TypeError): return html.escape(str(value))

    if derived_data.get('total_wins') is not None:
        parts.append(f"  👑 Перемог/Поразок: <b>{derived_data['total_wins']} / {derived_data.get('total_losses', 'N/A')}</b>")
        has_data = True
    if derived_data.get('mvp_rate_percent') is not None:
        parts.append(f"  ⭐ MVP Рейтинг: <b>{_format_derived_value(derived_data['mvp_rate_percent'])}%</b> матчів")
        has_data = True
    # ... (решта показників унікальної аналітики) ...
    if derived_data.get('mvp_win_share_percent') is not None:
        parts.append(f"  🏆 Частка MVP у перемогах: <b>{_format_derived_value(derived_data['mvp_win_share_percent'])}%</b>")
        has_data = True
    if derived_data.get('savage_frequency_per_1000_matches') is not None:
        parts.append(f"  🔥 Частота Savage: ~<b>{_format_derived_value(derived_data['savage_frequency_per_1000_matches'])}</b> на 1000 матчів")
        has_data = True
    if derived_data.get('legendary_frequency_per_100_matches') is not None:
        parts.append(f"  ✨ Частота Legendary: ~<b>{_format_derived_value(derived_data['legendary_frequency_per_100_matches'])}</b> на 100 матчів")
        has_data = True
    if derived_data.get('damage_per_gold_ratio') is not None:
        parts.append(f"  ⚔️ Ефективність золота: <b>{_format_derived_value(derived_data['damage_per_gold_ratio'])}</b> шкоди/хв на 1 золото/хв")
        has_data = True
    if derived_data.get('avg_impact_score_per_match') is not None:
        parts.append(f"  🎯 Сер. Вплив (K+A)/матч: ~<b>{_format_derived_value(derived_data['avg_impact_score_per_match'])}</b>")
        has_data = True
    if not has_data: return f"Для гравця {user_name_escaped} недостатньо даних для розрахунку унікальної аналітики."
    return "\n".join(parts)

# === ОБРОБКА КОЛБЕКІВ ===
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not (cq_msg := callback_query.message) or not cq_msg.chat: # cq_msg = callback_query.message
        logger.error("trigger_vision_analysis_callback: відсутнє повідомлення або чат у колбеку.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear()
        return

    chat_id = cq_msg.chat.id
    message_id_with_photo = cq_msg.message_id # Це ID повідомлення, яке бот надіслав з фото та кнопками
    
    user_data = await state.get_data()
    user_name_original = user_data.get("original_user_name", "Гравець") 
    user_name_escaped = html.escape(user_name_original)
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")
    analysis_type = user_data.get("analysis_type")

    if not all([photo_file_id, vision_prompt, analysis_type]):
        logger.error(f"Недостатньо даних у стані для аналізу для {user_name_original} (ID: {callback_query.from_user.id}).")
        error_text = f"Помилка, {user_name_escaped}: дані для аналізу втрачено. Спробуйте надіслати скріншот знову."
        try:
            # Спочатку видаляємо кнопки, якщо вони є
            if cq_msg.reply_markup:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_with_photo, reply_markup=None)
            # Потім редагуємо підпис або надсилаємо нове повідомлення
            if cq_msg.caption: # Якщо є підпис (наприклад, "Скріншот отримано...")
                 await cq_msg.edit_caption(caption=error_text)
            elif cq_msg.photo: # Якщо є фото, але немає підпису (малоймовірно, але можливо)
                 await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_with_photo, caption=error_text)
            else: # Якщо повідомлення не фото (дуже малоймовірно на цьому етапі)
                 await bot.send_message(chat_id, error_text)
        except TelegramAPIError as e_clear:
            logger.warning(f"Помилка при спробі оновити повідомлення про втрату даних для {user_name_original}: {e_clear}")
        await state.clear()
        return

    try: # Оновлюємо повідомлення з фото, прибираючи кнопки та встановлюючи текст "Обробляю..."
        if cq_msg.caption:
            await cq_msg.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {user_name_escaped}...",
                reply_markup=None 
            )
        elif cq_msg.reply_markup : # Якщо немає підпису, але є кнопки
            await cq_msg.edit_reply_markup(reply_markup=None)
        # Якщо ні підпису, ні кнопок, але стан активний - просто відповідаємо на колбек
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name_original} (ID: {callback_query.from_user.id}): {e}")

    full_analysis_text_parts = []
    # Текст помилки за замовчуванням, якщо щось піде не так
    default_error_text = f"😔 Вибач, {user_name_escaped}, сталася непередбачена помилка при обробці зображення."

    try:
        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path: raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")
        downloaded_file_io = await bot.download_file(file_info.file_path)
        if downloaded_file_io is None: raise ValueError("Не вдалося завантажити файл з Telegram (download_file повернув None).")
        
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз ({analysis_type}) для {user_name_original} (ID: {callback_query.from_user.id}).")
                
                if analysis_type == "profile":
                    structured_data_text = format_profile_result(user_name_original, analysis_result_json)
                    description_text = await gpt_analyzer.get_profile_description(user_name_original, analysis_result_json)
                    
                    full_analysis_text_parts.append(structured_data_text)
                    if description_text and description_text.strip():
                        full_analysis_text_parts.append(f"\n\n{html.escape(description_text)}")
                
                elif analysis_type == "player_stats":
                    derived_stats = calculate_derived_stats(analysis_result_json)
                    data_for_description = analysis_result_json.copy()
                    if derived_stats: data_for_description['derived_stats'] = derived_stats 
                    
                    commentary_raw = await gpt_analyzer.get_player_stats_description(user_name_original, data_for_description)
                    if commentary_raw and commentary_raw.strip():
                        # Додаємо коментар тільки якщо він не є повідомленням про помилку від GPT
                        if not ("<i>" in commentary_raw and "</i>" in commentary_raw):
                            full_analysis_text_parts.append(f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(commentary_raw)}")
                        else: # Якщо це заглушка/помилка від GPT, додаємо як є
                            full_analysis_text_parts.append(commentary_raw)
                    
                    unique_analytics_formatted = format_unique_analytics_text(user_name_original, derived_stats)
                    # Додаємо унікальну аналітику, якщо вона не є повідомленням про помилку
                    if unique_analytics_formatted and "недостатньо даних" not in unique_analytics_formatted.lower() and "не вдалося розрахувати" not in unique_analytics_formatted.lower():
                        full_analysis_text_parts.append(f"\n\n{unique_analytics_formatted}")
                    
                    detailed_stats_formatted = format_detailed_stats_text(user_name_original, analysis_result_json)
                    full_analysis_text_parts.append(f"\n\n{detailed_stats_formatted}")
                else:
                    logger.warning(f"Невідомий тип аналізу: {analysis_type} для {user_name_original} (ID: {callback_query.from_user.id})")
                    full_analysis_text_parts.append(f"Не вдалося обробити результати: невідомий тип аналізу, {user_name_escaped}.")

            else: # Помилка від Vision API
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу ({analysis_type}) для {user_name_original} (ID: {callback_query.from_user.id}): {error_msg}.")
                error_text_for_user = f"😔 Вибач, {user_name_escaped}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
                if analysis_result_json and (raw_snippet := analysis_result_json.get("raw_response") or analysis_result_json.get("details")):
                    error_text_for_user += f"\nДеталі: {html.escape(str(raw_snippet)[:150])}..."
                full_analysis_text_parts.append(error_text_for_user)
    
    except TelegramAPIError as e:
        logger.exception(f"Telegram API помилка під час обробки файлу для {user_name_original} (ID: {callback_query.from_user.id}): {e}")
        full_analysis_text_parts.append(f"Пробач, {user_name_escaped}, виникла проблема з доступом до файлу скріншота в Telegram.")
    except ValueError as e:
        logger.exception(f"Помилка значення під час обробки файлу для {user_name_original} (ID: {callback_query.from_user.id}): {e}")
        full_analysis_text_parts.append(f"На жаль, {user_name_escaped}, не вдалося коректно обробити файл скріншота.")
    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота ({analysis_type}) для {user_name_original} (ID: {callback_query.from_user.id}): {e}")
        full_analysis_text_parts.append(default_error_text)

    # --- НАДСИЛАННЯ ОБ'ЄДНАНОГО РЕЗУЛЬТАТУ ---
    final_text_to_send = "\n".join(filter(None, full_analysis_text_parts)).strip()
    if not final_text_to_send: # Якщо з якихось причин текст порожній, використовуємо помилку за замовчуванням
        final_text_to_send = default_error_text

    try:
        # Переконуємося, що повідомлення, яке ми редагуємо, все ще існує і є фото
        if cq_msg and cq_msg.photo: 
            if len(final_text_to_send) <= MAX_TELEGRAM_MESSAGE_LENGTH: # Ліміт підпису до фото
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id_with_photo,
                    caption=final_text_to_send, parse_mode=ParseMode.HTML
                )
                logger.info(f"Результати аналізу ({analysis_type}) для {user_name_original} відредаговано в підписі до фото (ID: {message_id_with_photo}).")
            else: # Підпис задовгий
                logger.warning(f"Підпис до фото ({analysis_type}) для {user_name_original} задовгий ({len(final_text_to_send)} символів). Очищую підпис фото і надсилаю текст окремо.")
                try: # Спробуємо очистити підпис "Обробляю..."
                    await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_with_photo, caption=" ") 
                except TelegramAPIError: pass # Ігноруємо, якщо не вдалося
                await send_message_in_chunks(bot, chat_id, final_text_to_send, ParseMode.HTML)
        else: # Якщо повідомлення, яке мало бути фото, вже не фото або не існує
            logger.info(f"Повідомлення (ID: {message_id_with_photo}), яке мало бути фото, не знайдено або не є фото. Надсилаю результат ({analysis_type}) для {user_name_original} окремим повідомленням.")
            await send_message_in_chunks(bot, chat_id, final_text_to_send, ParseMode.HTML)

    except TelegramAPIError as e: # Помилка при фінальному надсиланні/редагуванні
        logger.error(f"Не вдалося відредагувати/надіслати фінальне повідомлення з результатами ({analysis_type}) для {user_name_original}: {e}")
        try: # Остання спроба надіслати хоч щось текстом
            await send_message_in_chunks(bot, chat_id, final_text_to_send, ParseMode.HTML)
        except Exception as send_err:
            logger.error(f"Критична помилка: не вдалося надіслати фінальне повідомлення ({analysis_type}) для {user_name_original}: {send_err}")
    
    await state.clear() 

# === ІНШІ ОБРОБНИКИ КОЛБЕКІВ ТА СТАНІВ ===
async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.message:
        logger.error("delete_bot_message_callback: callback_query.message is None.")
        await callback_query.answer("Помилка видалення.", show_alert=True)
        return
    try:
        await callback_query.message.delete()
        await callback_query.answer("Повідомлення видалено.")
        current_state_str = await state.get_state()
        if current_state_str == VisionAnalysisStates.awaiting_analysis_trigger.state:
            user_data = await state.get_data()
            user_name_original = user_data.get("original_user_name", f"Користувач (ID: {callback_query.from_user.id})")
            logger.info(f"Прев'ю аналізу видалено користувачем {html.escape(user_name_original)}. Стан очищено.")
            await state.clear()
        else:
            logger.info(f"Повідомлення бота видалено користувачем (ID: {callback_query.from_user.id}). Поточний стан: {current_state_str}")
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота для користувача (ID: {callback_query.from_user.id}): {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)

async def cancel_analysis(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user: return 
    user_name_original = message.from_user.first_name
    user_name_escaped = html.escape(user_name_original)
    logger.info(f"Користувач {user_name_escaped} (ID: {message.from_user.id}) скасував аналіз зображення командою /cancel.")
    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id and message.chat: 
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            logger.info(f"Видалено повідомлення-прев'ю бота (ID: {bot_message_id}) після скасування аналізу {user_name_escaped}.")
        except TelegramAPIError:
            logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота (ID: {bot_message_id}) при скасуванні для {user_name_escaped}.")
    await state.clear()
    await message.reply(f"Аналіз зображення скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go або іншу.")

async def handle_wrong_input_for_analysis(message: Message, state: FSMContext, bot: Bot, cmd_go_handler_func) -> None:
    if not message.from_user: return
    user_name_original = message.from_user.first_name
    user_name_escaped = html.escape(user_name_original)
    user_id = message.from_user.id
    
    if message.text and message.text.lower() == "/cancel":
        await cancel_analysis(message, state, bot)
        return
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data()
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try: await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError: pass 
        await state.clear()
        await cmd_go_handler_func(message, state) 
        return
        
    current_state_name = await state.get_state()
    user_data = await state.get_data()
    analysis_type_display = html.escape(user_data.get("analysis_type", "невідомого типу"))

    if current_state_name == VisionAnalysisStates.awaiting_profile_screenshot.state:
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав не фото у стані awaiting_profile_screenshot (для аналізу типу: {analysis_type_display}).")
        await message.reply(f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) для аналізу {analysis_type_display} або команду /cancel для скасування.")
    elif current_state_name == VisionAnalysisStates.awaiting_analysis_trigger.state:
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав '{html.escape(message.text or 'не текстове повідомлення')}' у стані awaiting_analysis_trigger.")
        await message.reply(f"Очікувалася дія з аналізом (кнопка під фото) або команда /cancel, {user_name_escaped}.")
    else: 
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав некоректне введення у непередбаченому стані аналізу ({current_state_name}).")
        await message.reply(f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.")

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None:
    """Реєструє всі обробники, пов'язані з аналізом зображень."""
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    dp.message.register(cmd_analyze_player_stats, Command("analyzestats"))
    
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    
    dp.callback_query.register(trigger_vision_analysis_callback, F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
    
    dp.callback_query.register(delete_bot_message_callback, F.data == "delete_bot_message")
    
    cancel_states = [
        VisionAnalysisStates.awaiting_profile_screenshot,
        VisionAnalysisStates.awaiting_analysis_trigger
    ]
    for cancel_state_item in cancel_states: 
        dp.message.register(cancel_analysis, cancel_state_item, Command("cancel"))
    
    wrong_input_handler_with_go_ref = lambda message, state, bot: handle_wrong_input_for_analysis(message, state, bot, cmd_go_handler_func)
    dp.message.register(wrong_input_handler_with_go_ref, VisionAnalysisStates.awaiting_profile_screenshot)
    dp.message.register(wrong_input_handler_with_go_ref, VisionAnalysisStates.awaiting_analysis_trigger)
    
    logger.info("Обробники аналізу зображень (профіль, статистика гравця) успішно зареєстровано.")