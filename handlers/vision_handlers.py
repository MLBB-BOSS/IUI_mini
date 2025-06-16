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
from config import OPENAI_API_KEY, logger # Використовуємо logger з config
from services.openai_service import (
    MLBBChatGPT,
    PROFILE_SCREENSHOT_PROMPT,
    PLAYER_STATS_PROMPT
)
from states.vision_states import VisionAnalysisStates
from utils.message_utils import send_message_in_chunks


# === ДОПОМІЖНА ФУНКЦІЯ ДЛЯ БЕЗПЕЧНОГО ОТРИМАННЯ ЧИСЕЛ ===
def _safe_get_float(data: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    """Безпечно отримує значення з словника та конвертує у float."""
    if data is None:
        return None
    value = data.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.debug(f"Не вдалося конвертувати '{value}' у float для ключа '{key}'")
        return None

def _safe_get_int(data: Optional[Dict[str, Any]], key: str) -> Optional[int]:
    """Безпечно отримує значення з словника та конвертує у int."""
    if data is None:
        return None
    value = data.get(key)
    if value is None:
        return None
    try:
        # Спочатку float для обробки чисел типу "2.0" або навіть рядків "2.0"
        return int(float(value))
    except (ValueError, TypeError):
        logger.debug(f"Не вдалося конвертувати '{value}' у int для ключа '{key}'")
        return None

# === РОЗРАХУНОК УНІКАЛЬНИХ СТАТИСТИК ===
def calculate_derived_stats(stats_data: Dict[str, Any]) -> Dict[str, Union[str, float, int, None]]:
    """
    Розраховує додаткові унікальні статистичні показники на основі даних від Vision API.
    """
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
    avg_hero_dmg_per_min = _safe_get_float(details_p, 'avg_hero_dmg_per_min') # Використовується int, але може бути float
    avg_gold_per_min = _safe_get_float(details_p, 'avg_gold_per_min') # Аналогічно

    # 1. Загальна кількість перемог/поразок
    if matches_played is not None and win_rate_percent is not None:
        total_wins = int(round(matches_played * (win_rate_percent / 100.0))) # Округлення для точності
        derived['total_wins'] = total_wins
        derived['total_losses'] = matches_played - total_wins
    else:
        derived['total_wins'] = None
        derived['total_losses'] = None

    # 2. MVP Рейтинг (%)
    if mvp_count is not None and matches_played is not None and matches_played > 0:
        derived['mvp_rate_percent'] = round((mvp_count / matches_played) * 100, 2)
    else:
        derived['mvp_rate_percent'] = None

    # 3. Частота Savage (на 1000 матчів)
    if savage_count is not None and matches_played is not None and matches_played > 0:
        derived['savage_frequency_per_1000_matches'] = round((savage_count / matches_played) * 1000, 2)
    else:
        derived['savage_frequency_per_1000_matches'] = None
        
    # 4. Частота Legendary (на 100 матчів)
    if legendary_count is not None and matches_played is not None and matches_played > 0:
        derived['legendary_frequency_per_100_matches'] = round((legendary_count / matches_played) * 100, 2)
    else:
        derived['legendary_frequency_per_100_matches'] = None

    # 5. Відсоток MVP у перемогах (MVP Win Share)
    if mvp_count is not None and mvp_count > 0 and mvp_loss_count is not None:
        mvp_wins = mvp_count - mvp_loss_count
        if mvp_wins > 0 : # Перевірка, що є MVP у перемогах
            derived['mvp_win_share_percent'] = round((mvp_wins / mvp_count) * 100, 2) # Рахуємо від загальної кількості MVP
        elif mvp_wins == 0 and mvp_count > 0: # Всі MVP були при поразках
             derived['mvp_win_share_percent'] = 0.0
        else: # Аномальні дані або mvp_wins < 0
            derived['mvp_win_share_percent'] = None
    else:
        derived['mvp_win_share_percent'] = None
        
    # 6. Ефективність золота (Шкода героям/хв / Золото/хв)
    if avg_hero_dmg_per_min is not None and avg_gold_per_min is not None and avg_gold_per_min > 0:
        derived['damage_per_gold_ratio'] = round(avg_hero_dmg_per_min / avg_gold_per_min, 2)
    else:
        derived['damage_per_gold_ratio'] = None
        
    # 7. Середній "Імпакт" (Вбивства + Допомоги) за матч
    if kda_ratio is not None and avg_deaths_per_match is not None:
        if avg_deaths_per_match > 0:
            # KDA = (K+A)/D  => K+A = KDA * D
            derived['avg_impact_score_per_match'] = round(kda_ratio * avg_deaths_per_match, 2)
        elif kda_ratio is not None: # Якщо смертей 0, гра часто показує KDA як K+A
             derived['avg_impact_score_per_match'] = round(kda_ratio, 2)
        else:
            derived['avg_impact_score_per_match'] = None
    else:
        derived['avg_impact_score_per_match'] = None
        
    logger.info(f"Розраховано унікальні статистики: {derived}")
    return derived

# === ОБРОБНИКИ КОМАНД ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzeprofile викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    user_id = user.id
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzeprofile.")
    await state.update_data(
        analysis_type="profile",
        vision_prompt=PROFILE_SCREENSHOT_PROMPT,
        original_user_name=user_name_escaped
    )
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
        "Будь ласка, надішли мені скріншот свого профілю з Mobile Legends для аналізу.\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzestats викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    user_id = user.id
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzestats.")
    await state.update_data(
        analysis_type="player_stats",
        vision_prompt=PLAYER_STATS_PROMPT,
        original_user_name=user_name_escaped
    )
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
        "Будь ласка, надішли мені скріншот своєї ігрової статистики (зазвичай розділ \"Statistics\" -> \"All Seasons\" або \"Current Season\").\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not message.chat:
        logger.error("handle_profile_screenshot: відсутній message.from_user або message.chat")
        return
    user_data_state = await state.get_data()
    user_name_escaped = user_data_state.get("original_user_name", html.escape(message.from_user.first_name if message.from_user else "Гравець"))
    user_id = message.from_user.id
    chat_id = message.chat.id
    logger.info(f"Отримано скріншот для аналізу від {user_name_escaped} (ID: {user_id}).")
    if not message.photo:
        await message.answer(f"Щось пішло не так, {user_name_escaped}. Будь ласка, надішли саме фото (скріншот).")
        return
    photo_file_id = message.photo[-1].file_id
    try:
        await message.delete() # Видаляємо оригінальне повідомлення користувача зі скріншотом
        logger.info(f"Повідомлення користувача {user_name_escaped} (ID: {user_id}) зі скріншотом видалено.")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped} (ID: {user_id}) зі скріншотом: {e}")
    
    await state.update_data(vision_photo_file_id=photo_file_id)
    caption_text = f"Скріншот отримано, {user_name_escaped}.\nНатисніть «🔍 Аналіз», щоб розпочати, або «🗑️ Видалити», щоб скасувати."
    analyze_button = InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")
    delete_preview_button = InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[analyze_button, delete_preview_button]])
    try:
        # Бот надсилає фото повторно з кнопками
        sent_message = await bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id, # Використовуємо file_id отриманого фото
            caption=caption_text,
            reply_markup=keyboard
        )
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
        logger.info(f"Скріншот від {user_name_escaped} (ID: {user_id}) повторно надіслано ботом з кнопками. Новий state: awaiting_analysis_trigger")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для аналізу для {user_name_escaped} (ID: {user_id}): {e}")
        try:
            await bot.send_message(chat_id, f"Не вдалося обробити ваш запит на аналіз, {user_name_escaped}. Спробуйте ще раз.")
        except TelegramAPIError as send_err: # Обробка помилки надсилання повідомлення про помилку
            logger.error(f"Не вдалося надіслати повідомлення про помилку обробки аналізу для {user_name_escaped} (ID: {user_id}): {send_err}")
        await state.clear()

# === ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ АНАЛІЗУ ПРОФІЛЮ ===
def format_profile_result(user_name: str, data: Dict[str, Any]) -> str:
    user_name_escaped = html.escape(user_name)
    if not data:
        return f"Не вдалося розпізнати дані профілю для {user_name_escaped}."
    response_parts = [f"<b>Детальний аналіз твого профілю, {user_name_escaped}:</b>"]
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
                if "★" not in display_value: # Стандартизація до ★
                        display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                display_value = re.sub(r'\s+★', '★', display_value) # Прибираємо зайві пробіли перед ★
            response_parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
            has_data = True
        else:
            response_parts.append(f"<b>{readable_name}:</b> <i>не розпізнано</i>")
    
    if not has_data and data.get("raw_response"): # Якщо нічого не розпізнано, але є сира відповідь
        response_parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>\nДеталі в raw_response Vision API.")
    elif not has_data: # Якщо нічого не розпізнано і немає сирої відповіді
        response_parts.append(f"\n<i>Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")
    return "\n".join(response_parts)

# === НОВІ ФУНКЦІЇ ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ АНАЛІЗУ СТАТИСТИКИ ===

def format_detailed_stats_text(user_name: str, data: Dict[str, Any]) -> str:
    """Форматує основну (детальну) статистику гравця у читабельний HTML."""
    user_name_escaped = html.escape(user_name)
    if not data:
        return f"Не вдалося розпізнати дані детальної статистики для {user_name_escaped}."
    
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
    """Форматує унікальну аналітику гравця у читабельний HTML."""
    user_name_escaped = html.escape(user_name)
    if not derived_data: # Якщо derived_data - None або порожній словник
        return f"Для гравця {user_name_escaped} недостатньо даних для розрахунку унікальної аналітики."

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
    
    if not has_data:
        return f"Для гравця {user_name_escaped} недостатньо даних для розрахунку унікальної аналітики."
        
    return "\n".join(parts)

# === ОБРОБКА КОЛБЕКІВ (НАТИСКАННЯ КНОПОК) ===
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear()
        return

    chat_id = callback_query.message.chat.id
    message_id_with_photo = callback_query.message.message_id 
    user_data = await state.get_data()
    user_name_original = user_data.get("original_user_name", "Гравець") # Не екрановане ім'я для логіки
    user_name_escaped = html.escape(user_name_original) # Екрановане для відображення

    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")
    analysis_type = user_data.get("analysis_type")

    if not photo_file_id or not vision_prompt or not analysis_type:
        logger.error(f"Недостатньо даних у стані для аналізу для {user_name_original} (ID: {callback_query.from_user.id}).")
        try:
            if callback_query.message and callback_query.message.reply_markup: # Видаляємо кнопки, якщо є
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_with_photo, reply_markup=None)
            
            error_text = f"Помилка, {user_name_escaped}: дані для аналізу втрачено або неповні. Спробуйте надіслати скріншот знову."
            if callback_query.message and callback_query.message.caption: # Якщо є підпис, редагуємо його
                 await callback_query.message.edit_caption(caption=error_text)
            else: # Якщо немає, надсилаємо нове повідомлення
                 await bot.send_message(chat_id, error_text)
        except TelegramAPIError as e_clear:
            logger.warning(f"Помилка при спробі оновити повідомлення про втрату даних для {user_name_original}: {e_clear}")
        await state.clear()
        return

    try:
        # Оновлюємо повідомлення з фото, прибираючи кнопки та встановлюючи текст "Обробляю..."
        if callback_query.message and callback_query.message.caption:
            await callback_query.message.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {user_name_escaped}...",
                reply_markup=None 
            )
        elif callback_query.message: # Якщо немає підпису, але є кнопки (малоймовірно)
            await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name_original} (ID: {callback_query.from_user.id}): {e}")

    # Змінна для фінального тексту (для "profile" або помилок, що не стосуються "player_stats")
    final_text_for_generic_send = f"Дуже шкода, {user_name_escaped}, але сталася непередбачена помилка при обробці зображення."

    try:
        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")
        downloaded_file_io = await bot.download_file(file_info.file_path)
        if downloaded_file_io is None:
            raise ValueError("Не вдалося завантажити файл з Telegram (download_file повернув None).")
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз ({analysis_type}) для {user_name_original} (ID: {callback_query.from_user.id}).")
                
                if analysis_type == "profile":
                    structured_data_text = format_profile_result(user_name_original, analysis_result_json)
                    description_text = await gpt_analyzer.get_profile_description(user_name_original, analysis_result_json)
                    final_text_for_generic_send = f"{structured_data_text}\n\n{html.escape(description_text)}"
                    # Для "profile" обробка продовжиться у загальному блоці надсилання в кінці
                
                elif analysis_type == "player_stats":
                    derived_stats = calculate_derived_stats(analysis_result_json)
                    
                    # 1. Генеруємо Коментар від IUI
                    data_for_description = analysis_result_json.copy()
                    if derived_stats: # Додаємо розраховану статистику для більш глибокого аналізу GPT
                        data_for_description['derived_stats'] = derived_stats 
                    
                    commentary_raw = await gpt_analyzer.get_player_stats_description(user_name_original, data_for_description)
                    commentary_to_send = ""
                    if commentary_raw and commentary_raw.strip():
                        if "<i>" in commentary_raw and "</i>" in commentary_raw: # Перевірка на повідомлення про помилку/заглушку від GPT
                            commentary_to_send = commentary_raw 
                        else:
                            commentary_to_send = f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(commentary_raw)}"
                    
                    # 2. Генеруємо Унікальну Аналітику
                    unique_analytics_formatted = format_unique_analytics_text(user_name_original, derived_stats)
                    
                    # 3. Генеруємо Детальну статистику (для підпису до фото)
                    detailed_stats_caption = format_detailed_stats_text(user_name_original, analysis_result_json)

                    # --- ПОСЛІДОВНЕ НАДСИЛАННЯ ПОВІДОМЛЕНЬ ДЛЯ PLAYER_STATS ---
                    if commentary_to_send:
                        await send_message_in_chunks(bot, chat_id, commentary_to_send, ParseMode.HTML)
                        logger.info(f"Надіслано коментар для {user_name_original}.")
                        await asyncio.sleep(0.2) 

                    if unique_analytics_formatted and "недостатньо даних" not in unique_analytics_formatted.lower() and "не вдалося розрахувати" not in unique_analytics_formatted.lower():
                         await send_message_in_chunks(bot, chat_id, unique_analytics_formatted, ParseMode.HTML)
                         logger.info(f"Надіслано унікальну аналітику для {user_name_original}.")
                         await asyncio.sleep(0.2)
                    
                    # Оновлюємо підпис до оригінального фото (повідомлення message_id_with_photo)
                    if callback_query.message and callback_query.message.photo:
                        if len(detailed_stats_caption) <= 1024: # Ліміт довжини підпису
                            try:
                                await bot.edit_message_caption(
                                    chat_id=chat_id,
                                    message_id=message_id_with_photo,
                                    caption=detailed_stats_caption,
                                    parse_mode=ParseMode.HTML
                                )
                                logger.info(f"Оновлено підпис до фото (детальна статистика) для {user_name_original}.")
                            except TelegramAPIError as e_caption:
                                logger.error(f"Не вдалося оновити підпис до фото детальної статистики для {user_name_original}: {e_caption}. Спробую надіслати текст окремо.")
                                await send_message_in_chunks(bot, chat_id, detailed_stats_caption, ParseMode.HTML)
                        else: # Якщо підпис задовгий
                            logger.warning(f"Підпис для детальної статистики ({user_name_original}) задовгий ({len(detailed_stats_caption)}). Надсилаю текст окремо.")
                            try: # Спробуємо видалити підпис "Обробляю..." або встановити порожній
                                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_with_photo, caption=" ") 
                            except TelegramAPIError: pass # Ігноруємо помилку, якщо не вдалося
                            await send_message_in_chunks(bot, chat_id, detailed_stats_caption, ParseMode.HTML)
                    else: 
                        logger.warning(f"Оригінальне повідомлення з фото (ID: {message_id_with_photo}) не знайдено або не є фото. Надсилаю детальну статистику текстом.")
                        await send_message_in_chunks(bot, chat_id, detailed_stats_caption, ParseMode.HTML)
                    
                    await state.clear() 
                    return # Завершуємо обробку для player_stats тут

                else: # Невідомий тип аналізу
                    logger.warning(f"Невідомий тип аналізу: {analysis_type} для {user_name_original} (ID: {callback_query.from_user.id})")
                    final_text_for_generic_send = f"Не вдалося обробити результати: невідомий тип аналізу, {user_name_escaped}."

            else: # Помилка від Vision API
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу ({analysis_type}) для {user_name_original} (ID: {callback_query.from_user.id}): {error_msg}. "
                             f"Деталі: {analysis_result_json.get('details') if analysis_result_json else 'N/A'}")
                final_text_for_generic_send = f"😔 Вибач, {user_name_escaped}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
                raw_resp_snippet = ""
                if analysis_result_json:
                    if analysis_result_json.get("raw_response"):
                        raw_resp_snippet = html.escape(str(analysis_result_json.get('raw_response'))[:150])
                    elif analysis_result_json.get("details"):
                        raw_resp_snippet = html.escape(str(analysis_result_json.get('details'))[:150])
                if raw_resp_snippet:
                     final_text_for_generic_send += f"\nДеталі: {raw_resp_snippet}..."
    
    except TelegramAPIError as e: # Помилки Telegram API під час завантаження файлу тощо
        logger.exception(f"Telegram API помилка під час обробки файлу для {user_name_original} (ID: {callback_query.from_user.id}): {e}")
        final_text_for_generic_send = f"Пробач, {user_name_escaped}, виникла проблема з доступом до файлу скріншота в Telegram."
    except ValueError as e: # Помилки при обробці даних, наприклад, відсутність file_path
        logger.exception(f"Помилка значення під час обробки файлу для {user_name_original} (ID: {callback_query.from_user.id}): {e}")
        final_text_for_generic_send = f"На жаль, {user_name_escaped}, не вдалося коректно обробити файл скріншота."
    except Exception as e: # Інші непередбачені помилки
        logger.exception(f"Критична помилка обробки скріншота ({analysis_type}) для {user_name_original} (ID: {callback_query.from_user.id}): {e}")
        # final_text_for_generic_send вже має значення за замовчуванням

    # --- ЗАГАЛЬНИЙ БЛОК НАДСИЛАННЯ РЕЗУЛЬТАТІВ (для "profile" або помилок, що не були оброблені вище) ---
    # Якщо analysis_type == "player_stats" і все пройшло успішно, ми вже зробили return.
    try:
        # Переконуємося, що кнопки видалені, якщо вони ще є і повідомлення існує
        if callback_query.message and callback_query.message.reply_markup:
             try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_with_photo, reply_markup=None)
             except TelegramAPIError: pass 

        if callback_query.message and callback_query.message.photo and len(final_text_for_generic_send) <= 1024:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id_with_photo,
                caption=final_text_for_generic_send, parse_mode=ParseMode.HTML
            )
            logger.info(f"Результати аналізу (тип: {analysis_type}, або помилка) для {user_name_original} відредаговано в підписі до фото.")
        elif callback_query.message and callback_query.message.photo and len(final_text_for_generic_send) > 1024:
             logger.warning(f"Підпис до фото ({analysis_type}) для {user_name_original} задовгий. Редагую фото, прибираючи підпис 'Обробляю...', і надсилаю текст окремо.")
             try: 
                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_with_photo, caption=" ") # Очищуємо підпис
             except TelegramAPIError: pass
             await send_message_in_chunks(bot, chat_id, final_text_for_generic_send, ParseMode.HTML)
        else: 
            logger.info(f"Повідомлення (ID: {message_id_with_photo}) не є фото або його немає. Надсилаю результат ({analysis_type}) окремим повідомленням.")
            await send_message_in_chunks(bot, chat_id, final_text_for_generic_send, ParseMode.HTML)
            # Якщо оригінальне повідомлення було фото, воно залишиться без підпису "Обробляю..." або з порожнім підписом.

    except TelegramAPIError as e: # Помилка при фінальному надсиланні/редагуванні
        logger.error(f"Не вдалося відредагувати/надіслати фінальне повідомлення з результатами ({analysis_type}) для {user_name_original}: {e}")
        try: # Остання спроба надіслати хоч щось текстом
            await send_message_in_chunks(bot, chat_id, final_text_for_generic_send, ParseMode.HTML)
        except Exception as send_err:
            logger.error(f"Критична помилка: не вдалося надіслати фінальне повідомлення ({analysis_type}) для {user_name_original}: {send_err}")
    
    await state.clear() # Очищуємо стан у будь-якому випадку в кінці

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
        # Якщо видаляється повідомлення з кнопками "Аналіз", очищуємо стан, щоб уникнути зависання
        if current_state_str == VisionAnalysisStates.awaiting_analysis_trigger.state:
            user_data = await state.get_data()
            user_name = user_data.get("original_user_name", f"Користувач (ID: {callback_query.from_user.id})")
            logger.info(f"Прев'ю аналізу видалено користувачем {user_name}. Стан очищено.")
            await state.clear()
        else:
            logger.info(f"Повідомлення бота видалено користувачем (ID: {callback_query.from_user.id}). Поточний стан: {current_state_str}")
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота для користувача (ID: {callback_query.from_user.id}): {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)

async def cancel_analysis(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user: return # Захист від повідомлень без користувача
    user_name_escaped = html.escape(message.from_user.first_name)
    logger.info(f"Користувач {user_name_escaped} (ID: {message.from_user.id}) скасував аналіз зображення командою /cancel.")
    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id and message.chat: # Перевірка наявності message.chat
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            logger.info(f"Видалено повідомлення-прев'ю бота (ID: {bot_message_id}) після скасування аналізу {user_name_escaped}.")
        except TelegramAPIError:
            logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота (ID: {bot_message_id}) при скасуванні для {user_name_escaped}.")
    await state.clear()
    await message.reply(f"Аналіз зображення скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go або іншу.")

async def handle_wrong_input_for_analysis(message: Message, state: FSMContext, bot: Bot, cmd_go_handler_func) -> None:
    if not message.from_user: return
    user_name_escaped = html.escape(message.from_user.first_name)
    user_id = message.from_user.id
    
    # Перевірка на /cancel перш за все
    if message.text and message.text.lower() == "/cancel":
        await cancel_analysis(message, state, bot)
        return
    # Перевірка на /go
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data()
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try: await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError: pass # Ігноруємо помилку видалення
        await state.clear()
        await cmd_go_handler_func(message, state) # Викликаємо переданий обробник /go
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
    else: # Непередбачений стан
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) надіслав некоректне введення у непередбаченому стані аналізу ({current_state_name}).")
        await message.reply(f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.")

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None:
    """Реєструє всі обробники, пов'язані з аналізом зображень."""
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    dp.message.register(cmd_analyze_player_stats, Command("analyzestats"))
    
    # Обробка фото у стані очікування скріншоту
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    
    # Обробка натискання кнопки "Аналіз"
    dp.callback_query.register(trigger_vision_analysis_callback, F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
    
    # Обробка натискання кнопки "Видалити" (для повідомлення-прев'ю)
    dp.callback_query.register(delete_bot_message_callback, F.data == "delete_bot_message")
    
    # Обробка команди /cancel у відповідних станах
    cancel_states = [
        VisionAnalysisStates.awaiting_profile_screenshot,
        VisionAnalysisStates.awaiting_analysis_trigger
    ]
    for cancel_state_item in cancel_states: # Уникаємо конфлікту імен
        dp.message.register(cancel_analysis, cancel_state_item, Command("cancel"))
    
    # Обробка некоректного вводу у станах аналізу
    # Створюємо lambda, щоб правильно передати cmd_go_handler_func
    wrong_input_handler_with_go_ref = lambda message, state, bot: handle_wrong_input_for_analysis(message, state, bot, cmd_go_handler_func)
    dp.message.register(wrong_input_handler_with_go_ref, VisionAnalysisStates.awaiting_profile_screenshot)
    dp.message.register(wrong_input_handler_with_go_ref, VisionAnalysisStates.awaiting_analysis_trigger)
    
    logger.info("Обробники аналізу зображень (профіль, статистика гравця) успішно зареєстровано.")
