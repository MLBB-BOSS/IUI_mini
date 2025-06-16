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
from utils.message_utils import send_message_in_chunks
import asyncio

# === КОНСТАНТИ ДЛЯ ФОРМАТУВАННЯ ===

class AnalysisFormatter:
    """Клас для форматування результатів аналізу з уніфікованою структурою."""
    
    @staticmethod
    def _create_header_section(title: str, icon: str = "📊") -> str:
        """Створює заголовок секції."""
        return f"\n<b>{icon} {title}</b>\n" + "─" * 30
    
    @staticmethod
    def _format_field(label: str, value: Any, icon: str = "•") -> str:
        """Форматує окреме поле з валідацією."""
        if value is None or value == "":
            return f"  {icon} <b>{label}:</b> <i>не розпізнано</i>"
        
        display_value = str(value)
        if "★" in display_value or "зірок" in display_value.lower():
            display_value = re.sub(r'\s+★', '★', display_value.replace("зірок", "★").replace("зірки", "★"))
        
        return f"  {icon} <b>{label}:</b> {html.escape(display_value)}"

# === ДОПОМІЖНА ФУНКЦІЯ ДЛЯ БЕЗПЕЧНОГО ОТРИМАННЯ ЧИСЕЛ ===

def _safe_get_float(data: Optional[Dict[str, Any]], key: str, default: float = 0.0) -> float:
    if data is None:
        return default
    value = data.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def _safe_get_int(data: Optional[Dict[str, Any]], key: str, default: int = 0) -> int:
    if data is None:
        return default
    value = data.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

# === РОЗРАХУНОК УНІКАЛЬНИХ СТАТИСТИК ===

def calculate_derived_stats(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Розраховує унікальні статистики на основі даних від Vision API."""
    if not data:
        return None

    main_ind = data.get("main_indicators", {})
    details_p = data.get("details_panel", {})
    ach_left = data.get("achievements_left_column", {})
    ach_right = data.get("achievements_right_column", {})

    derived = {}

    # Загальна кількість перемог та поразок
    matches_played = _safe_get_int(main_ind, 'matches_played')
    win_rate = _safe_get_float(main_ind, 'win_rate')
    if matches_played > 0 and win_rate > 0:
        derived['total_wins'] = int(matches_played * win_rate / 100)
        derived['total_losses'] = matches_played - derived['total_wins']

    # MVP Рейтинг (% матчів, де гравець був MVP)
    mvp_count = _safe_get_int(main_ind, 'mvp_count')
    if matches_played > 0 and mvp_count is not None:
        derived['mvp_rate_percent'] = (mvp_count / matches_played) * 100

    # Частка MVP у перемогах (% перемог, де гравець був MVP)
    if derived.get('total_wins', 0) > 0 and mvp_count is not None:
        derived['mvp_win_share_percent'] = (mvp_count / derived['total_wins']) * 100

    # Частота Savage на 1000 матчів
    savage_count = _safe_get_int(ach_right, 'savage_count')
    if matches_played > 0 and savage_count is not None:
        derived['savage_frequency_per_1000_matches'] = (savage_count / matches_played) * 1000

    # Частота Legendary на 100 матчів
    legendary_count = _safe_get_int(ach_left, 'legendary_count')
    if matches_played > 0 and legendary_count is not None:
        derived['legendary_frequency_per_100_matches'] = (legendary_count / matches_played) * 100

    # Ефективність золота (шкода/золото)
    avg_hero_dmg_per_min = _safe_get_float(details_p, 'avg_hero_dmg_per_min')
    avg_gold_per_min = _safe_get_float(details_p, 'avg_gold_per_min')
    if avg_gold_per_min > 0 and avg_hero_dmg_per_min is not None:
        derived['damage_per_gold_ratio'] = round(avg_hero_dmg_per_min / avg_gold_per_min, 2)

    # Середній вплив (K+A)/матч
    kda_ratio = _safe_get_float(details_p, 'kda_ratio')
    if kda_ratio > 0 and matches_played > 0:
        avg_deaths_per_match = _safe_get_float(details_p, 'avg_deaths_per_match')
        if avg_deaths_per_match > 0:
            derived['avg_impact_score_per_match'] = round(kda_ratio * avg_deaths_per_match, 2)

    return derived if derived else None

# === ОБРОБНИКИ КОМАНД ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===

async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    """
    Обробник команди /analyzeprofile. 
    Запитує скріншот профілю гравця для аналізу.
    """
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
        "Якщо передумаєш, просто надішли команду /cancel.",
        parse_mode=ParseMode.HTML
    )

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    """
    Обробник команди /analyzestats.
    Запитує скріншот загальної статистики гравця для аналізу.
    """
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
        "Якщо передумаєш, просто надішли команду /cancel.",
        parse_mode=ParseMode.HTML
    )

# === ОБРОБКА НАДСИЛАННЯ ЗОБРАЖЕНЬ ===

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    """
    Обробляє надісланий скріншот для будь-якого типу аналізу.
    Видаляє повідомлення користувача та створює превью з кнопками.
    """
    if not message.from_user or not message.chat:
        logger.error("handle_profile_screenshot: відсутній message.from_user або message.chat")
        return

    user_data_state = await state.get_data()
    user_name_escaped = user_data_state.get("original_user_name", html.escape(message.from_user.first_name))
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    logger.info(f"Отримано скріншот для аналізу від {user_name_escaped} (ID: {user_id}).")

    if not message.photo: 
        await message.answer(f"Щось пішло не так, {user_name_escaped}. Будь ласка, надішли саме фото (скріншот).")
        return

    photo_file_id = message.photo[-1].file_id 

    try:
        await message.delete()
        logger.info(f"Повідомлення користувача {user_name_escaped} (ID: {user_id}) зі скріншотом видалено.")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped}: {e}")

    await state.update_data(vision_photo_file_id=photo_file_id)

    caption_text = "Скріншот отримано.\nНатисніть «🔍 Аналіз», щоб дізнатися більше, або «🗑️ Видалити», щоб скасувати операцію."

    analyze_button = InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")
    delete_preview_button = InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[analyze_button, delete_preview_button]])

    try:
        sent_message = await bot.send_photo( 
            chat_id=chat_id,
            photo=photo_file_id,
            caption=caption_text,
            reply_markup=keyboard
        )
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
        logger.info(f"Скріншот від {user_name_escaped} (ID: {user_id}) повторно надіслано ботом з кнопками.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для {user_name_escaped}: {e}")
        await bot.send_message(chat_id, f"Не вдалося обробити ваш запит на аналіз, {user_name_escaped}.")
        await state.clear()

# === ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ АНАЛІЗУ ===

def format_profile_result(user_name: str, data: Dict[str, Any]) -> str:
    """
    Форматує результати аналізу профілю.
    """
    if not data:
        return f"Не вдалося розпізнати дані профілю для {html.escape(user_name)}."

    parts = [f"<b>📋 Профіль гравця {html.escape(user_name)}:</b>"]
    
    fields = {
        "game_nickname": "🎮 Нікнейм",
        "mlbb_id_server": "🆔 ID (Сервер)",
        "highest_rank_season": "🌟 Найвищий ранг",
        "matches_played": "⚔️ Матчів зіграно",
        "likes_received": "👍 Лайків отримано",
        "location": "🌍 Локація",
        "squad_name": "🛡️ Сквад"
    }
    
    has_data = False
    for key, label in fields.items():
        value = data.get(key)
        if value is not None:
            parts.append(AnalysisFormatter._format_field(label, value))
            has_data = True
    
    if not has_data:
        parts.append("<i>⚠️ Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")
    
    return "\n".join(parts)

def format_detailed_stats_text(user_name: str, data: Dict[str, Any]) -> str:
    """Форматує детальну статистику гравця у читабельний HTML."""
    if not data:
        return f"Не вдалося розпізнати дані детальної статистики для {html.escape(user_name)}."
    
    parts = [f"<b>📊 Детальна статистика гравця {html.escape(user_name)} ({html.escape(str(data.get('stats_filter_type', 'N/A')))}):</b>"]

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
    if not derived_data:
        return f"Не вдалося розрахувати унікальну аналітику для {html.escape(user_name)}."

    parts = [f"<b>📈 <u>Унікальна Аналітика від IUI для {html.escape(user_name)}:</u></b>"]
    
    has_data = False

    total_wins = derived_data.get('total_wins')
    total_losses = derived_data.get('total_losses', 'N/A')
    if total_wins is not None:
        parts.append(f"  👑 Перемог/Поразок: <b>{total_wins} / {total_losses}</b>")
        has_data = True
    
    mvp_rate = derived_data.get('mvp_rate_percent')
    if mvp_rate is not None:
        parts.append(f"  ⭐ MVP Рейтинг: <b>{mvp_rate:.2f}%</b> матчів")
        has_data = True
        
    mvp_win_share = derived_data.get('mvp_win_share_percent')
    if mvp_win_share is not None:
        parts.append(f"  🏆 Частка MVP у перемогах: <b>{mvp_win_share:.2f}%</b>")
        has_data = True
        
    savage_freq = derived_data.get('savage_frequency_per_1000_matches')
    if savage_freq is not None:
        parts.append(f"  🔥 Частота Savage: ~<b>{savage_freq:.2f}</b> на 1000 матчів")
        has_data = True
        
    legendary_freq = derived_data.get('legendary_frequency_per_100_matches')
    if legendary_freq is not None:
        parts.append(f"  ✨ Частота Legendary: ~<b>{legendary_freq:.2f}</b> на 100 матчів")
        has_data = True
        
    dmg_gold_ratio = derived_data.get('damage_per_gold_ratio')
    if dmg_gold_ratio is not None:
        parts.append(f"  ⚔️ Ефективність золота: <b>{dmg_gold_ratio:.2f}</b> шкоди/хв на 1 золото/хв")
        has_data = True
        
    avg_impact = derived_data.get('avg_impact_score_per_match')
    if avg_impact is not None:
        parts.append(f"  🎯 Сер. Вплив (K+A)/матч: ~<b>{avg_impact:.2f}</b>")
        has_data = True
    
    if not has_data:
        return f"Для гравця {html.escape(user_name)} недостатньо даних для розрахунку унікальної аналітики."
        
    return "\n".join(parts)

# === ОБРОБКА КОЛБЕКІВ (НАТИСКАННЯ КНОПОК) ===

async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """
    Обробляє натискання кнопки "Аналіз".
    Викликає Vision API та надсилає результати у заданій послідовності.
    """
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear()
        return

    chat_id = callback_query.message.chat.id
    message_id_with_photo = callback_query.message.message_id
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")
    analysis_type = user_data.get("analysis_type")

    if not photo_file_id or not vision_prompt or not analysis_type:
        logger.error(f"Недостатньо даних у стані для аналізу для {user_name} (ID: {callback_query.from_user.id}).")
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_with_photo, reply_markup=None)
            if callback_query.message.caption:
                await callback_query.message.edit_caption(caption=f"Помилка, {html.escape(user_name)}: дані для аналізу втрачено або неповні. Спробуйте надіслати скріншот знову.")
            else:
                await bot.send_message(chat_id, f"Помилка, {html.escape(user_name)}: дані для аналізу втрачено або неповні. Спробуйте надіслати скріншот знову.")
        except TelegramAPIError as e_clear:
            logger.warning(f"Помилка при спробі оновити повідомлення про втрату даних: {e_clear}")
        await state.clear()
        return

    try:
        if callback_query.message.caption:
            await callback_query.message.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {html.escape(user_name)}...",
                reply_markup=None
            )
        else:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name}: {e}")

    final_text_for_generic_send = f"Дуже шкода, {html.escape(user_name)}, але сталася непередбачена помилка при обробці зображення."

    try:
        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")
        downloaded_file_io = await bot.download_file(file_info.file_path)
        if downloaded_file_io is None:
            raise ValueError("Не вдалося завантажити файл з Telegram для аналізу.")
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз ({analysis_type}) для {user_name} (ID: {callback_query.from_user.id}).")
                
                if analysis_type == "profile":
                    structured_data_text = format_profile_result(user_name, analysis_result_json)
                    description_text = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                    final_text_for_generic_send = f"{structured_data_text}\n\n{html.escape(description_text)}"
                
                elif analysis_type == "player_stats":
                    derived_stats = calculate_derived_stats(analysis_result_json)
                    
                    # 1. Генеруємо Коментар від IUI
                    data_for_description = analysis_result_json.copy()
                    if derived_stats:
                        data_for_description['derived_stats'] = derived_stats 
                    commentary_raw = await gpt_analyzer.get_player_stats_description(user_name, data_for_description)
                    
                    commentary_to_send = ""
                    if "<i>" in commentary_raw and "</i>" in commentary_raw:
                        commentary_to_send = commentary_raw
                    elif commentary_raw.strip():
                        commentary_to_send = f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(commentary_raw)}"
                    
                    # 2. Генеруємо Унікальну Аналітику
                    unique_analytics_formatted = format_unique_analytics_text(user_name, derived_stats)
                    
                    # 3. Генеруємо Детальну статистику
                    detailed_stats_caption = format_detailed_stats_text(user_name, analysis_result_json)

                    # Послідовне надсилання повідомлень
                    if commentary_to_send:
                        await send_message_in_chunks(bot, chat_id, commentary_to_send, ParseMode.HTML)
                        await asyncio.sleep(0.2)

                    if unique_analytics_formatted and "недостатньо даних" not in unique_analytics_formatted.lower() and "не вдалося розрахувати" not in unique_analytics_formatted.lower():
                        await send_message_in_chunks(bot, chat_id, unique_analytics_formatted, ParseMode.HTML)
                        await asyncio.sleep(0.2)
                    
                    if callback_query.message and callback_query.message.photo:
                        if len(detailed_stats_caption) <= 1024:
                            try:
                                await bot.edit_message_caption(
                                    chat_id=chat_id,
                                    message_id=message_id_with_photo,
                                    caption=detailed_stats_caption,
                                    parse_mode=ParseMode.HTML
                                )
                                logger.info(f"Оновлено підпис до фото (детальна статистика) для {user_name}.")
                            except TelegramAPIError as e_caption:
                                logger.error(f"Не вдалося оновити підпис до фото: {e_caption}. Надсилаю текст окремо.")
                                await send_message_in_chunks(bot, chat_id, detailed_stats_caption, ParseMode.HTML)
                        else:
                            logger.warning(f"Підпис для детальної статистики задовгий ({len(detailed_stats_caption)}). Надсилаю текст окремо.")
                            try:
                                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_with_photo, caption=" ")
                            except TelegramAPIError:
                                pass
                            await send_message_in_chunks(bot, chat_id, detailed_stats_caption, ParseMode.HTML)
                    else:
                        logger.warning("Оригінальне повідомлення з фото не знайдено. Надсилаю детальну статистику текстом.")
                        await send_message_in_chunks(bot, chat_id, detailed_stats_caption, ParseMode.HTML)
                    
                    await state.clear()
                    return

                else:
                    logger.warning(f"Невідомий тип аналізу: {analysis_type} для {user_name} (ID: {callback_query.from_user.id})")
                    final_text_for_generic_send = f"Не вдалося обробити результати: невідомий тип аналізу, {html.escape(user_name)}."

            else:
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу ({analysis_type}) для {user_name} (ID: {callback_query.from_user.id}): {error_msg}.")
                final_text_for_generic_send = f"😔 Вибач, {html.escape(user_name)}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"

    except TelegramAPIError as e:
        logger.exception(f"Telegram API помилка під час обробки файлу для {user_name}: {e}")
        final_text_for_generic_send = f"Пробач, {html.escape(user_name)}, виникла проблема з доступом до файлу скріншота в Telegram."
    except ValueError as e:
        logger.exception(f"Помилка значення під час обробки файлу для {user_name}: {e}")
        final_text_for_generic_send = f"На жаль, {html.escape(user_name)}, не вдалося коректно обробити файл скріншота."
    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота ({analysis_type}) для {user_name}: {e}")

    # Загальний блок надсилання для "profile" або помилок
    try:
        if callback_query.message and callback_query.message.reply_markup:
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_with_photo, reply_markup=None)
            except TelegramAPIError:
                pass

        if callback_query.message and callback_query.message.photo and len(final_text_for_generic_send) <= 1024:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id_with_photo,
                caption=final_text_for_generic_send, parse_mode=ParseMode.HTML
            )
            logger.info(f"Результати аналізу (тип: {analysis_type}, або помилка) для {user_name} відредаговано в підписі до фото.")
        elif callback_query.message and callback_query.message.photo and len(final_text_for_generic_send) > 1024:
            logger.warning(f"Підпис до фото ({analysis_type}) для {user_name} задовгий. Надсилаю текст окремо.")
            try:
                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id_with_photo, caption=" ")
            except TelegramAPIError:
                pass
            await send_message_in_chunks(bot, chat_id, final_text_for_generic_send, ParseMode.HTML)
        else:
            logger.info(f"Надсилаю результат ({analysis_type}) окремим повідомленням.")
            await send_message_in_chunks(bot, chat_id, final_text_for_generic_send, ParseMode.HTML)

    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати/надіслати повідомлення з результатами аналізу для {user_name}: {e}")
        try:
            await send_message_in_chunks(bot, chat_id, final_text_for_generic_send, ParseMode.HTML)
        except Exception as send_err:
            logger.error(f"Критична помилка: не вдалося надіслати фінальне повідомлення для {user_name}: {send_err}")
    
    await state.clear()

async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    """Обробляє натискання кнопки "Видалити" на прев'ю скріншота."""
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
            user_name = user_data.get("original_user_name", f"Користувач (ID: {callback_query.from_user.id})")
            logger.info(f"Прев'ю аналізу видалено користувачем {user_name}. Стан очищено.")
            await state.clear()
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота: {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)

# === ОБРОБКА СКАСУВАННЯ ТА НЕКОРЕКТНОГО ВВЕДЕННЯ ===

async def cancel_analysis(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обробник команди /cancel під час аналізу зображення."""
    if not message.from_user:
        return

    user_name_escaped = html.escape(message.from_user.first_name)
    logger.info(f"Користувач {user_name_escaped} (ID: {message.from_user.id}) скасував аналіз зображення.")

    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    
    if bot_message_id and message.chat:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            logger.info(f"Видалено повідомлення-прев'ю бота після скасування аналізу {user_name_escaped}")
        except TelegramAPIError:
            logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота при скасуванні для {user_name_escaped}")

    await state.clear()
    await message.reply(
        f"Аналіз зображення скасовано, {user_name_escaped}. "
        "Ти можеш продовжити використовувати команду /go або інші функції бота.",
        parse_mode=ParseMode.HTML
    )

async def handle_wrong_input_for_analysis(message: Message, state: FSMContext, bot: Bot, cmd_go_handler_func) -> None:
    """Обробляє некоректне введення під час очікування скріншота або тригера аналізу."""
    if not message.from_user:
        return

    user_name_escaped = html.escape(message.from_user.first_name)
    user_id = message.from_user.id

    if message.text and message.text.lower() == "/cancel":
        await cancel_analysis(message, state, bot)
        return

    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) ввів /go у стані аналізу.")
        user_data = await state.get_data()
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError:
                pass
        await state.clear()
        await cmd_go_handler_func(message, state)
        return

    current_state_name = await state.get_state()
    user_data = await state.get_data()
    analysis_type_display = user_data.get("analysis_type", "невідомого типу")

    if current_state_name == VisionAnalysisStates.awaiting_profile_screenshot.state:
        logger.info(f"Користувач {user_name_escaped} надіслав не фото у стані awaiting_profile_screenshot")
        await message.reply(
            f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) для аналізу {analysis_type_display} "
            "або команду /cancel для скасування.",
            parse_mode=ParseMode.HTML
        )
    elif current_state_name == VisionAnalysisStates.awaiting_analysis_trigger.state:
        logger.info(f"Користувач {user_name_escaped} надіслав некоректне повідомлення у стані awaiting_analysis_trigger")
        await message.reply(
            f"Очікувалася дія з аналізом (кнопка під фото) або команда /cancel, {user_name_escaped}.",
            parse_mode=ParseMode.HTML
        )
    else:
        logger.info(f"Користувач {user_name_escaped} надіслав некоректне введення у непередбаченому стані аналізу")
        await message.reply(
            f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.",
            parse_mode=ParseMode.HTML
        )

# === РЕЄСТРАЦІЯ ОБРОБНИКІВ ===

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None:
    """Реєструє всі обробники, пов'язані з аналізом зображень."""
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    dp.message.register(cmd_analyze_player_stats, Command("analyzestats"))
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    dp.callback_query.register(
        trigger_vision_analysis_callback, 
        F.data == "trigger_vision_analysis", 
        VisionAnalysisStates.awaiting_analysis_trigger
    )
    dp.callback_query.register(delete_bot_message_callback, F.data == "delete_bot_message")
    cancel_states = [
        VisionAnalysisStates.awaiting_profile_screenshot,
        VisionAnalysisStates.awaiting_analysis_trigger
    ]
    for cancel_state in cancel_states:
        dp.message.register(cancel_analysis, cancel_state, Command("cancel"))
    wrong_input_handler_with_go = lambda message, state, bot: handle_wrong_input_for_analysis(
        message, state, bot, cmd_go_handler_func
    )
    dp.message.register(wrong_input_handler_with_go, VisionAnalysisStates.awaiting_profile_screenshot)
    dp.message.register(wrong_input_handler_with_go, VisionAnalysisStates.awaiting_analysis_trigger)
    logger.info("Обробники аналізу зображень зареєстровано.")