import asyncio
import base64
import html
import logging 
import re
import random 
from typing import Dict, Any, Optional, Union

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest 
from aiogram.fsm.context import FSMContext

from config import OPENAI_API_KEY, logger # Переконайся, що logger імпортується з config
from services.openai_service import (
    MLBBChatGPT,
    PROFILE_SCREENSHOT_PROMPT,
    PLAYER_STATS_PROMPT
)
from states.vision_states import VisionAnalysisStates
from utils.message_utils import send_message_in_chunks, MAX_TELEGRAM_MESSAGE_LENGTH 

PROCESSING_MESSAGES = [
    "🔎 Сканую ваш скріншот, хвилинку...",
    "🤖 Машинне навчання в дії! Аналізую...",
    "📊 Розшифровую цифри та показники...",
    "🧠 Проводжу глибокий аналіз даних...",
    "✨ Збираю найцікавіші інсайти для вас...",
    "⚡ Майже готово, фінальні штрихи...",
    "💡 Генерую ваш персоналізований звіт...",
    "🧐 Вивчаю деталі вашого профілю...",
    "📉 Обчислюю ключові метрики...",
    "✍️ Формую експертний висновок..."
]

# --- ДОПОМІЖНІ ФУНКЦІЇ (без змін) ---
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
    try: return int(float(value)) # Спочатку float, потім int для універсальності
    except (ValueError, TypeError):
        logger.debug(f"Не вдалося конвертувати '{value}' у int для ключа '{key}'")
        return None

def calculate_derived_stats(stats_data: Dict[str, Any]) -> Dict[str, Union[str, float, int, None]]:
    """Розраховує похідні статистики на основі наданих даних."""
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
    else:
        derived.update({'total_wins': None, 'total_losses': None})

    if mvp_count is not None and matches_played is not None and matches_played > 0:
        derived['mvp_rate_percent'] = round((mvp_count / matches_played) * 100, 2)
    else:
        derived['mvp_rate_percent'] = None

    if savage_count is not None and matches_played is not None and matches_played > 0:
        derived['savage_frequency_per_1000_matches'] = round((savage_count / matches_played) * 1000, 2)
    else:
        derived['savage_frequency_per_1000_matches'] = None
        
    if legendary_count is not None and matches_played is not None and matches_played > 0:
        derived['legendary_frequency_per_100_matches'] = round((legendary_count / matches_played) * 100, 2)
    else:
        derived['legendary_frequency_per_100_matches'] = None

    if mvp_count is not None and mvp_loss_count is not None: # mvp_count може бути 0
        if mvp_count > 0:
            mvp_wins = mvp_count - mvp_loss_count
            # mvp_wins може бути від'ємним, якщо mvp_loss_count > mvp_count (хоча це дивно)
            # Тому обробляємо цей випадок, але логічно mvp_wins не має бути < 0
            derived['mvp_win_share_percent'] = round((mvp_wins / mvp_count) * 100, 2) if mvp_wins >=0 else 0.0 # Або None, якщо mvp_wins < 0
        elif mvp_count == 0 and mvp_loss_count == 0 : # Якщо 0 MVP і 0 MVP Loss
            derived['mvp_win_share_percent'] = None # Або 0.0, залежно від бажаної логіки
        else: # mvp_count == 0, але mvp_loss_count > 0 (нелогічно, але можливо в даних)
            derived['mvp_win_share_percent'] = None 
    else:
        derived['mvp_win_share_percent'] = None
        
    if avg_hero_dmg_per_min is not None and avg_gold_per_min is not None and avg_gold_per_min > 0:
        derived['damage_per_gold_ratio'] = round(avg_hero_dmg_per_min / avg_gold_per_min, 2)
    else:
        derived['damage_per_gold_ratio'] = None
        
    if kda_ratio is not None and avg_deaths_per_match is not None:
        # Якщо avg_deaths_per_match = 0, KDA може бути високим. (K+A)/1 або просто K+A.
        # (K+A)/D. Якщо D=0, то KDA нескінченне. У грі зазвичай показують K+A якщо D=0.
        # Тут avg_impact_score_per_match = kda_ratio * avg_deaths_per_match. Якщо avg_deaths_per_match=0, то і результат 0.
        # Можливо, потрібна інша логіка для avg_impact_score_per_match.
        if avg_deaths_per_match > 0:
            derived['avg_impact_score_per_match'] = round(kda_ratio * avg_deaths_per_match, 2)
        elif kda_ratio is not None: # Якщо смертей 0, то KDA = K+A. Вплив = K+A.
            derived['avg_impact_score_per_match'] = round(kda_ratio, 2) # Якщо KDA вже (K+A)/1
        else:
            derived['avg_impact_score_per_match'] = None
    else:
        derived['avg_impact_score_per_match'] = None
        
    # logger.info(f"Розраховано унікальні статистики: {derived}")
    return derived

# --- ОБРОБНИКИ КОМАНД (без змін) ---
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzeprofile викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    await state.update_data(analysis_type="profile", vision_prompt=PROFILE_SCREENSHOT_PROMPT, original_user_name=user.first_name)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nБудь ласка, надішли мені скріншот свого профілю для аналізу.\nЯкщо передумаєш, просто надішли команду /cancel.")

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzestats викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    await state.update_data(analysis_type="player_stats", vision_prompt=PLAYER_STATS_PROMPT, original_user_name=user.first_name)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nБудь ласка, надішли скріншот своєї ігрової статистики (розділ \"Statistics\" -> \"All Seasons\" або \"Current Season\").\nЯкщо передумаєш, просто надішли команду /cancel.")

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обробляє отриманий скріншот, видаляє повідомлення користувача, надсилає фото назад з кнопками."""
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
    chat_id_for_photo = message.chat.id # Зберігаємо chat_id для надсилання фото

    try:
        await message.delete()
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped} (ID: {message.from_user.id}): {e}")
    
    await state.update_data(vision_photo_file_id=photo_file_id)
    caption_text = f"Скріншот отримано, {user_name_escaped}.\nНатисніть «🔍 Аналіз» або «🗑️ Видалити»."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")],
        [InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")]
    ])
    
    try:
        sent_message = await bot.send_photo(
            chat_id=chat_id_for_photo, # Використовуємо збережений chat_id
            photo=photo_file_id, 
            caption=caption_text, 
            reply_markup=keyboard,
            business_connection_id=None # Явно вказуємо
        )
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id, chat_id_for_analysis=chat_id_for_photo)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для {user_name_escaped} (ID: {message.from_user.id}): {e}")
        try:
            await bot.send_message(chat_id_for_photo, f"Не вдалося обробити запит, {user_name_escaped}. Спробуйте ще раз.")
        except TelegramAPIError as send_err:
            logger.error(f"Не вдалося надіслати повідомлення про помилку для {user_name_escaped} (ID: {message.from_user.id}): {send_err}")
        await state.clear()

# --- ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ (без змін) ---
def format_profile_result(user_name: str, data: Dict[str, Any]) -> str:
    user_name_escaped = html.escape(user_name)
    if not data: return f"Не вдалося розпізнати дані профілю для {user_name_escaped}."
    parts = [f"<b>Детальний аналіз твого профілю, {user_name_escaped}:</b>"]
    fields_translation = {"game_nickname": "🎮 Нікнейм","mlbb_id_server": "🆔 ID (Сервер)","highest_rank_season": "🌟 Найвищий ранг (сезон)","matches_played": "⚔️ Матчів зіграно","likes_received": "👍 Лайків отримано","location": "🌍 Локація","squad_name": "🛡️ Сквад"}
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
    if not has_data and data.get("raw_response"): parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>")
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
        parts.append(f"  👑 Перемог/Поразок: <b>{derived_data['total_wins']} / {derived_data.get('total_losses', 'N/A')}</b>"); has_data = True
    if derived_data.get('mvp_rate_percent') is not None:
        parts.append(f"  ⭐ MVP Рейтинг: <b>{_format_derived_value(derived_data['mvp_rate_percent'])}%</b> матчів"); has_data = True
    if derived_data.get('mvp_win_share_percent') is not None:
        parts.append(f"  🏆 Частка MVP у перемогах: <b>{_format_derived_value(derived_data['mvp_win_share_percent'])}%</b>"); has_data = True
    if derived_data.get('savage_frequency_per_1000_matches') is not None:
        parts.append(f"  🔥 Частота Savage: ~<b>{_format_derived_value(derived_data['savage_frequency_per_1000_matches'])}</b> на 1000 матчів"); has_data = True
    if derived_data.get('legendary_frequency_per_100_matches') is not None:
        parts.append(f"  ✨ Частота Legendary: ~<b>{_format_derived_value(derived_data['legendary_frequency_per_100_matches'])}</b> на 100 матчів"); has_data = True
    if derived_data.get('damage_per_gold_ratio') is not None:
        parts.append(f"  ⚔️ Ефективність золота: <b>{_format_derived_value(derived_data['damage_per_gold_ratio'])}</b> шкоди/хв на 1 золото/хв"); has_data = True
    if derived_data.get('avg_impact_score_per_match') is not None:
        parts.append(f"  🎯 Сер. Вплив (K+A)/матч: ~<b>{_format_derived_value(derived_data['avg_impact_score_per_match'])}</b>"); has_data = True
    if not has_data: return f"Для гравця {user_name_escaped} недостатньо даних для розрахунку унікальної аналітики."
    return "\n".join(parts)

# --- ОБРОБКА КОЛБЕКІВ ---
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Обробляє натискання кнопки 'Аналіз', виконує аналіз зображення та оновлює повідомлення."""
    if not (cq_msg := callback_query.message) or not cq_msg.chat : # cq_msg = callback_query.message
        logger.error("trigger_vision_analysis_callback: відсутнє повідомлення або чат у колбеку.")
        try:
            await callback_query.answer("Помилка: не вдалося обробити запит (відсутнє повідомлення).", show_alert=True)
        except TelegramAPIError: pass # Якщо і відповідь не вдалася
        await state.clear()
        return

    # Отримуємо chat_id з cq_msg.chat.id, а не зі стану, для більшої надійності на цьому етапі
    chat_id_from_cq = cq_msg.chat.id
    message_id_from_cq = cq_msg.message_id

    user_data = await state.get_data()
    user_name_original = user_data.get("original_user_name", "Гравець") 
    user_name_escaped = html.escape(user_name_original)
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")
    analysis_type = user_data.get("analysis_type")
    
    # Перевіряємо, чи всі необхідні дані є в стані
    if not all([photo_file_id, vision_prompt, analysis_type, user_name_original]):
        logger.error(f"Недостатньо даних у стані для аналізу для користувача {callback_query.from_user.id}. Дані: {user_data}")
        error_text = f"Помилка, {user_name_escaped}: дані для аналізу втрачено. Спробуйте надіслати скріншот знову."
        try:
            if cq_msg.reply_markup: 
                await bot.edit_message_reply_markup(chat_id=chat_id_from_cq, message_id=message_id_from_cq, reply_markup=None, business_connection_id=None)
            if cq_msg.photo and cq_msg.caption is not None:
                 await bot.edit_message_caption(chat_id=chat_id_from_cq, message_id=message_id_from_cq, caption=error_text, business_connection_id=None)
            else: 
                 await bot.send_message(chat_id_from_cq, error_text) # Надсилаємо нове, якщо cq_msg не фото
        except TelegramAPIError as e_clear:
            logger.warning(f"Помилка при спробі оновити/надіслати повідомлення про втрату даних для {user_name_original}: {e_clear}")
        await state.clear()
        return

    last_edit_time = 0 
    current_loop = asyncio.get_event_loop()

    async def _edit_caption_robust(target_chat_id: int, target_message_id: int, caption_text: str) -> bool:
        """Надійна функція для редагування підпису з контролем частоти та обробкою помилок."""
        nonlocal last_edit_time
        min_interval = 1.0 # Мінімальний інтервал між редагуваннями
        now = current_loop.time()
        
        if now - last_edit_time < min_interval:
            await asyncio.sleep(min_interval - (now - last_edit_time))
        
        try:
            await bot.edit_message_caption(
                chat_id=target_chat_id, 
                message_id=target_message_id, 
                caption=caption_text,
                parse_mode=ParseMode.HTML, # Дозволяємо HTML у проміжних повідомленнях
                business_connection_id=None
            )
            last_edit_time = current_loop.time()
            return True
        except TelegramBadRequest as e: 
            if "message is not modified" in str(e).lower():
                logger.debug(f"Підпис не змінено (той самий текст): '{caption_text[:30]}...'")
                last_edit_time = current_loop.time() 
                return True 
            logger.warning(f"Не вдалося оновити підпис на '{caption_text[:30]}...': {e} (BadRequest)")
            return False
        except TelegramAPIError as e: 
            logger.error(f"API помилка при оновленні підпису на '{caption_text[:30]}...': {e}")
            return False

    # --- Початкове оновлення повідомлення ---
    try:
        initial_processing_text = f"⏳ {random.choice(PROCESSING_MESSAGES)} {user_name_escaped}..."
        # Видаляємо кнопки перед першим редагуванням підпису
        if cq_msg.reply_markup:
            await bot.edit_message_reply_markup(chat_id=chat_id_from_cq, message_id=message_id_from_cq, reply_markup=None, business_connection_id=None)
        
        if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, initial_processing_text):
             raise TelegramAPIError("Не вдалося встановити початковий підпис 'Обробляю...'.")
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення на 'Обробляю...' або видалити кнопки для {user_name_original}: {e}")
        try: await callback_query.answer("Помилка ініціалізації аналізу.") # Відповідь, якщо ще не було
        except TelegramAPIError: pass # Ігноруємо, якщо answer вже був
        await state.clear() # Очищуємо стан, якщо не можемо навіть почати
        return

    full_analysis_text_parts: list[str] = []
    default_error_text = f"😔 Вибач, {user_name_escaped}, сталася непередбачена помилка під час обробки зображення."
    can_edit_cq_msg_flag = True 

    try:
        if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, f"🖼️ Завантажую скріншот, {user_name_escaped}..."):
            can_edit_cq_msg_flag = False; raise ValueError("Повідомлення для редагування недоступне (етап завантаження).")

        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path: raise ValueError("Не вдалося отримати шлях до файлу зображення.")
        downloaded_file_io = await bot.download_file(file_info.file_path)
        if downloaded_file_io is None: raise ValueError("Не вдалося завантажити файл зображення з Telegram.")
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, f"🤖 Відправляю на аналіз до Vision AI, {user_name_escaped}..."):
                can_edit_cq_msg_flag = False; raise ValueError("Повідомлення недоступне перед запитом до Vision AI.")
            
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз ({analysis_type}) для {user_name_original}.")
                if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, f"📊 Обробляю результати аналізу, {user_name_escaped}..."):
                    can_edit_cq_msg_flag = False; raise ValueError("Повідомлення недоступне після аналізу Vision AI.")

                if analysis_type == "profile":
                    structured_data_text = format_profile_result(user_name_original, analysis_result_json)
                    if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, f"✍️ Генерую опис профілю, {user_name_escaped}..."):
                         can_edit_cq_msg_flag = False; raise ValueError("Повідомлення недоступне перед генерацією опису профілю.")
                    description_text = await gpt_analyzer.get_profile_description(user_name_original, analysis_result_json)
                    full_analysis_text_parts.append(structured_data_text)
                    if description_text and description_text.strip():
                        full_analysis_text_parts.append(f"\n\n{html.escape(description_text)}")
                
                elif analysis_type == "player_stats":
                    if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, f"📈 Розраховую унікальну статистику, {user_name_escaped}..."):
                        can_edit_cq_msg_flag = False; raise ValueError("Повідомлення недоступне перед розрахунком статистики.")
                    derived_stats = calculate_derived_stats(analysis_result_json)
                    data_for_description = {**analysis_result_json, 'derived_stats': derived_stats or {}}
                    
                    if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, f"🎙️ Створюю коментар від IUI, {user_name_escaped}..."):
                        can_edit_cq_msg_flag = False; raise ValueError("Повідомлення недоступне перед генерацією коментаря.")
                    commentary_raw = await gpt_analyzer.get_player_stats_description(user_name_original, data_for_description)
                    
                    if commentary_raw and commentary_raw.strip():
                        is_error_like_comment = "<i>" in commentary_raw and "</i>" in commentary_raw or \
                                               "error" in commentary_raw.lower() or \
                                               "помилка" in commentary_raw.lower()
                        if not is_error_like_comment:
                            full_analysis_text_parts.append(f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(commentary_raw)}")
                        elif "<i>" in commentary_raw and "</i>" in commentary_raw : # Додаємо тільки якщо це форматована заглушка
                             full_analysis_text_parts.append(commentary_raw)
                    
                    unique_analytics_formatted = format_unique_analytics_text(user_name_original, derived_stats)
                    if unique_analytics_formatted and "недостатньо даних" not in unique_analytics_formatted.lower() and "не вдалося розрахувати" not in unique_analytics_formatted.lower():
                        full_analysis_text_parts.append(f"\n\n{unique_analytics_formatted}")
                    
                    detailed_stats_formatted = format_detailed_stats_text(user_name_original, analysis_result_json)
                    full_analysis_text_parts.append(f"\n\n{detailed_stats_formatted}")
                else: 
                    logger.warning(f"Невідомий тип аналізу: {analysis_type} для {user_name_original}.")
                    full_analysis_text_parts.append(f"Не вдалося обробити результати: невідомий тип аналізу, {user_name_escaped}.")
            else: 
                error_msg = analysis_result_json.get('error', 'Невідома помилка Vision API.') if isinstance(analysis_result_json, dict) else 'Відповідь від Vision API не отримана або не є словником.'
                logger.error(f"Помилка Vision API ({analysis_type}) для {user_name_original}: {error_msg}")
                error_text_for_user = f"😔 Вибач, {user_name_escaped}, помилка аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
                if isinstance(analysis_result_json, dict) and (raw_snippet := analysis_result_json.get("raw_response") or analysis_result_json.get("details")):
                    error_text_for_user += f"\nДеталі: {html.escape(str(raw_snippet)[:150])}..."
                full_analysis_text_parts.append(error_text_for_user)
    
    except TelegramAPIError as e: 
        logger.exception(f"Telegram API помилка під час обробки або оновлення повідомлення для {user_name_original}: {e}")
        can_edit_cq_msg_flag = False
        if not full_analysis_text_parts: full_analysis_text_parts.append(f"Пробач, {user_name_escaped}, виникла проблема з Telegram під час обробки.")
    except ValueError as e:
        logger.warning(f"Помилка значення для {user_name_original} (можливо, повідомлення для редагування недоступне): {e}")
        can_edit_cq_msg_flag = False 
        if not full_analysis_text_parts: full_analysis_text_parts.append(f"На жаль, {user_name_escaped}, не вдалося коректно обробити запит. {html.escape(str(e))}")
    except Exception as e:
        logger.exception(f"Критична помилка обробки ({analysis_type}) для {user_name_original}: {e}")
        can_edit_cq_msg_flag = False
        if not full_analysis_text_parts: full_analysis_text_parts.append(default_error_text)

    final_text_to_send = "\n".join(filter(None, full_analysis_text_parts)).strip()
    if not final_text_to_send: final_text_to_send = default_error_text 

    try:
        if can_edit_cq_msg_flag and cq_msg and cq_msg.photo: 
            if len(final_text_to_send) <= MAX_TELEGRAM_MESSAGE_LENGTH:
                if not await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, final_text_to_send):
                    logger.warning(f"Не вдалося фінально відредагувати підпис для {user_name_original}. Надсилаю новим повідомленням.")
                    await send_message_in_chunks(bot, chat_id_from_cq, final_text_to_send, ParseMode.HTML)
                else:
                     logger.info(f"Результати аналізу ({analysis_type}) для {user_name_original} ВІДРЕДАГОВАНО в підписі до фото (ID: {message_id_from_cq}).")
            else: 
                logger.warning(f"Підпис до фото ({analysis_type}) для {user_name_original} задовгий. Оновлюю підпис фото і надсилаю текст окремо.")
                final_caption_for_photo = f"✅ Аналіз завершено, {user_name_escaped}! Деталі нижче 👇"
                await _edit_caption_robust(chat_id_from_cq, message_id_from_cq, final_caption_for_photo)
                await send_message_in_chunks(bot, chat_id_from_cq, final_text_to_send, ParseMode.HTML)
        else: 
            logger.info(f"Повідомлення (ID: {message_id_from_cq if cq_msg else 'N/A'}) не вдалося фінально відредагувати або воно не є фото. Надсилаю результат ({analysis_type}) для {user_name_original} окремим повідомленням.")
            await send_message_in_chunks(bot, chat_id_from_cq, final_text_to_send, ParseMode.HTML)
    except Exception as e: 
        logger.error(f"Критична помилка при фінальному надсиланні/редагуванні ({analysis_type}) для {user_name_original} (ID: {message_id_from_cq if cq_msg else 'N/A'}): {e}. Спроба надіслати новим.")
        try: 
            await send_message_in_chunks(bot, chat_id_from_cq, final_text_to_send, ParseMode.HTML)
        except Exception as send_err:
            logger.error(f"Критична помилка: не вдалося надіслати фінальне повідомлення ({analysis_type}) для {user_name_original} після помилки редагування: {send_err}")
    
    await state.clear() 

# --- ІНШІ ОБРОБНИКИ (без змін) ---
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
    chat_id_for_cancel = user_data.get("chat_id_for_analysis", message.chat.id) # Використовуємо збережений chat_id або з поточного повідомлення
    if bot_message_id and chat_id_for_cancel: 
        try:
            await bot.delete_message(chat_id=chat_id_for_cancel, message_id=bot_message_id)
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
        chat_id_for_wrong_input = user_data.get("chat_id_for_analysis", message.chat.id)
        if bot_message_id and chat_id_for_wrong_input:
            try: await bot.delete_message(chat_id=chat_id_for_wrong_input, message_id=bot_message_id)
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
    cancel_states = [VisionAnalysisStates.awaiting_profile_screenshot, VisionAnalysisStates.awaiting_analysis_trigger]
    for cancel_state_item in cancel_states: 
        dp.message.register(cancel_analysis, cancel_state_item, Command("cancel"))
    
    # Створюємо частково застосовану функцію для передачі cmd_go_handler_func
    # Це потрібно, якщо cmd_go_handler_func очікує більше аргументів, ніж надає хендлер
    async def wrong_input_wrapper(message: Message, state: FSMContext, bot_instance: Bot): # Перейменовано bot на bot_instance
        await handle_wrong_input_for_analysis(message, state, bot_instance, cmd_go_handler_func)

    dp.message.register(wrong_input_wrapper, VisionAnalysisStates.awaiting_profile_screenshot)
    dp.message.register(wrong_input_wrapper, VisionAnalysisStates.awaiting_analysis_trigger)
    
    logger.info("Обробники аналізу зображень (профіль, статистика гравця) успішно зареєстровано.")
