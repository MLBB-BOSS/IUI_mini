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


# === ОБРОБНИКИ КОМАНД ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===

async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    """
    Обробник команди /analyzeprofile. 
    Запитує скріншот профілю гравця для аналізу.
    
    Args:
        message: Повідомлення від користувача
        state: FSM контекст для збереження стану
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
    
    Args:
        message: Повідомлення від користувача
        state: FSM контекст для збереження стану
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
    
    Args:
        message: Повідомлення з фото від користувача
        state: FSM контекст
        bot: Екземпляр бота
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

    # Видаляємо оригінальне повідомлення користувача
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
        await _send_error_message(bot, chat_id, user_name_escaped, "Не вдалося обробити ваш запит на аналіз")
        await state.clear()

# === ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ АНАЛІЗУ ===

def format_profile_result(user_name: str, data: Dict[str, Any], ai_comment: Optional[str] = None) -> str:
    """
    Форматує результати аналізу профілю згідно з новою структурою.
    
    Args:
        user_name: Ім'я користувача
        data: Дані профілю від ШІ
        ai_comment: Коментар від ШІ (опціонально)
    
    Returns:
        Відформатований HTML текст
    """
    if not data:
        return f"Не вдалося розпізнати дані профілю для {user_name}."

    # Структура згідно з вимогами: 1. Коментар 2. Аналітика 3. Детальна статистика
    result_parts = []
    
    # 1. 🎙️ Коментар від IUI
    if ai_comment:
        result_parts.append(AnalysisFormatter._create_header_section("Коментар від IUI", "🎙️"))
        result_parts.append(f"<i>{html.escape(ai_comment)}</i>")
    
    # 2. 📈 Унікальна Аналітика від IUI
    result_parts.append(AnalysisFormatter._create_header_section("Унікальна Аналітика від IUI", "📈"))
    analytics = _generate_profile_analytics(data)
    result_parts.append(analytics)
    
    # 3. 📊 Детальна статистика гравця
    result_parts.append(AnalysisFormatter._create_header_section("Детальна статистика гравця", "📊"))
    
    # Основні дані профілю
    fields_translation = {
        "game_nickname": ("🎮 Нікнейм", "🎮"),
        "mlbb_id_server": ("🆔 ID (Сервер)", "🆔"), 
        "highest_rank_season": ("🌟 Найвищий ранг", "🌟"),
        "matches_played": ("⚔️ Матчів зіграно", "⚔️"),
        "likes_received": ("👍 Лайків отримано", "👍"),
        "location": ("🌍 Локація", "🌍"),
        "squad_name": ("🛡️ Сквад", "🛡️")
    }
    
    has_data = False
    for key, (readable_name, icon) in fields_translation.items():
        value = data.get(key)
        if value is not None:
            result_parts.append(AnalysisFormatter._format_field(readable_name, value, icon))
            has_data = True
        else:
            result_parts.append(AnalysisFormatter._format_field(readable_name, None, icon))
    
    if not has_data and data.get("raw_response"):
        result_parts.append(f"\n<i>⚠️ Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>")
        result_parts.append(f"<code>{html.escape(str(data.get('raw_response'))[:200])}...</code>")
    elif not has_data:
        result_parts.append(f"\n<i>⚠️ Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")
    
    return "\n".join(result_parts)

def format_player_stats_result(user_name: str, data: Dict[str, Any], ai_comment: Optional[str] = None) -> str:
    """
    Форматує результати аналізу статистики згідно з новою структурою.
    
    Args:
        user_name: Ім'я користувача
        data: Дані статистики від ШІ
        ai_comment: Коментар від ШІ (опціонально)
        
    Returns:
        Відформатований HTML текст
    """
    if not data:
        return f"Не вдалося розпізнати дані статистики для {user_name}."

    result_parts = []
    
    # 1. 🎙️ Коментар від IUI
    if ai_comment:
        result_parts.append(AnalysisFormatter._create_header_section("Коментар від IUI", "🎙️"))
        result_parts.append(f"<i>{html.escape(ai_comment)}</i>")
    
    # 2. 📈 Унікальна Аналітика від IUI
    result_parts.append(AnalysisFormatter._create_header_section("Унікальна Аналітика від IUI", "📈"))
    analytics = _generate_stats_analytics(data)
    result_parts.append(analytics)
    
    # 3. 📊 Детальна статистика гравця
    result_parts.append(AnalysisFormatter._create_header_section(f"Детальна статистика гравця {user_name}", "📊"))
    
    stats_filter = data.get('stats_filter_type', 'N/A')
    result_parts.append(f"<b>📋 Тип статистики:</b> {html.escape(str(stats_filter))}")
    
    # Основні показники
    main_ind = data.get("main_indicators", {})
    if main_ind:
        result_parts.append(f"\n<b><u>⚡ Основні показники:</u></b>")
        result_parts.append(AnalysisFormatter._format_field("Матчів зіграно", main_ind.get('matches_played'), "🎯"))
        
        win_rate = main_ind.get('win_rate')
        if win_rate is not None:
            result_parts.append(AnalysisFormatter._format_field("Відсоток перемог", f"{win_rate}%", "🏆"))
        else:
            result_parts.append(AnalysisFormatter._format_field("Відсоток перемог", None, "🏆"))
            
        result_parts.append(AnalysisFormatter._format_field("MVP", main_ind.get('mvp_count'), "👑"))
    
    # Досягнення (ліва колонка)
    ach_left = data.get("achievements_left_column", {})
    if ach_left:
        result_parts.append(f"\n<b><u>🏅 Досягнення (Колонка 1):</u></b>")
        achievements_left = [
            ("Легендарних", ach_left.get('legendary_count'), "🔥"),
            ("Маніяків", ach_left.get('maniac_count'), "😈"),
            ("Подвійних вбивств", ach_left.get('double_kill_count'), "⚔️"),
            ("Найб. вбивств за гру", ach_left.get('most_kills_in_one_game'), "💀"),
            ("Найдовша серія перемог", ach_left.get('longest_win_streak'), "🔥"),
            ("Найб. шкоди/хв", ach_left.get('highest_dmg_per_min'), "💥"),
            ("Найб. золота/хв", ach_left.get('highest_gold_per_min'), "💰")
        ]
        
        for label, value, icon in achievements_left:
            result_parts.append(AnalysisFormatter._format_field(label, value, icon))
    
    # Досягнення (права колонка)
    ach_right = data.get("achievements_right_column", {})
    if ach_right:
        result_parts.append(f"\n<b><u>🎖️ Досягнення (Колонка 2):</u></b>")
        achievements_right = [
            ("Дикунств (Savage)", ach_right.get('savage_count'), "🔥"),
            ("Потрійних вбивств", ach_right.get('triple_kill_count'), "⚔️"),
            ("MVP при поразці", ach_right.get('mvp_loss_count'), "💔"),
            ("Найб. допомоги за гру", ach_right.get('most_assists_in_one_game'), "🤝"),
            ("Перша кров", ach_right.get('first_blood_count'), "🩸"),
            ("Найб. отриманої шкоди/хв", ach_right.get('highest_dmg_taken_per_min'), "🛡️")
        ]
        
        for label, value, icon in achievements_right:
            result_parts.append(AnalysisFormatter._format_field(label, value, icon))
    
    # Деталі (права панель)
    details = data.get("details_panel", {})
    if details:
        result_parts.append(f"\n<b><u>📋 Деталі (Права панель):</u></b>")
        details_fields = [
            ("KDA", details.get('kda_ratio'), "⚔️"),
            ("Участь у ком. боях", f"{details.get('teamfight_participation_rate')}%" if details.get('teamfight_participation_rate') is not None else None, "🤝"),
            ("Сер. золото/хв", details.get('avg_gold_per_min'), "💰"),
            ("Сер. шкода героям/хв", details.get('avg_hero_dmg_per_min'), "💥"),
            ("Сер. смертей/матч", details.get('avg_deaths_per_match'), "💀"),
            ("Сер. шкода вежам/матч", details.get('avg_turret_dmg_per_match'), "🏗️")
        ]
        
        for label, value, icon in details_fields:
            result_parts.append(AnalysisFormatter._format_field(label, value, icon))
    
    return "\n".join(result_parts)

def _generate_profile_analytics(data: Dict[str, Any]) -> str:
    """Генерує унікальну аналітику для профілю."""
    analytics = []
    
    # Аналіз рангу
    rank = data.get("highest_rank_season")
    if rank:
        if "mythic" in str(rank).lower() or "міфічний" in str(rank).lower():
            analytics.append("🔮 <b>Статус:</b> Досвідчений гравець вищого рівня")
        elif "legend" in str(rank).lower() or "легенда" in str(rank).lower():
            analytics.append("⭐ <b>Статус:</b> Сильний гравець з хорошими навичками")
        elif "epic" in str(rank).lower() or "епік" in str(rank).lower():
            analytics.append("💎 <b>Статус:</b> Гравець середнього рівня")
        else:
            analytics.append("🌱 <b>Статус:</b> Гравець, що розвивається")
    
    # Аналіз активності
    matches = data.get("matches_played")
    if matches:
        try:
            matches_num = int(str(matches).replace(',', '').replace(' ', ''))
            if matches_num > 5000:
                analytics.append("🎮 <b>Активність:</b> Надзвичайно активний гравець")
            elif matches_num > 2000:
                analytics.append("🎮 <b>Активність:</b> Дуже активний гравець")
            elif matches_num > 1000:
                analytics.append("🎮 <b>Активність:</b> Регулярний гравець")
            else:
                analytics.append("🎮 <b>Активність:</b> Помірний гравець")
        except ValueError:
            analytics.append("🎮 <b>Активність:</b> Дані потребують уточнення")
    
    # Аналіз популярності
    likes = data.get("likes_received")
    if likes:
        try:
            likes_num = int(str(likes).replace(',', '').replace(' ', ''))
            if likes_num > 1000:
                analytics.append("👥 <b>Популярність:</b> Високо оцінений спільнотою")
            elif likes_num > 500:
                analytics.append("👥 <b>Популярність:</b> Добре відомий в спільноті")
            else:
                analytics.append("👥 <b>Популярність:</b> Будує репутацію")
        except ValueError:
            analytics.append("👥 <b>Популярність:</b> Дані потребують уточнення")
    
    if not analytics:
        analytics.append("📈 Базова аналітика недоступна через недостатність даних")
    
    return "\n".join(analytics)

def _generate_stats_analytics(data: Dict[str, Any]) -> str:
    """Генерує унікальну аналітику для статистики."""
    analytics = []
    
    main_ind = data.get("main_indicators", {})
    details = data.get("details_panel", {})
    
    # Аналіз ефективності
    win_rate = main_ind.get('win_rate')
    if win_rate is not None:
        try:
            wr_num = float(str(win_rate).replace('%', ''))
            if wr_num >= 70:
                analytics.append("🏆 <b>Ефективність:</b> Виняткова (топ-гравець)")
            elif wr_num >= 60:
                analytics.append("🏆 <b>Ефективність:</b> Відмінна (skilled)")
            elif wr_num >= 50:
                analytics.append("🏆 <b>Ефективність:</b> Хороша (стабільний)")
            else:
                analytics.append("🏆 <b>Ефективність:</b> Потребує покращення")
        except ValueError:
            analytics.append("🏆 <b>Ефективність:</b> Дані потребують уточнення")
    
    # Аналіз KDA
    kda = details.get('kda_ratio')
    if kda:
        try:
            kda_num = float(str(kda))
            if kda_num >= 3.0:
                analytics.append("⚔️ <b>Майстерність бою:</b> Відмінна (високий KDA)")
            elif kda_num >= 2.0:
                analytics.append("⚔️ <b>Майстерність бою:</b> Хороша")
            elif kda_num >= 1.5:
                analytics.append("⚔️ <b>Майстерність бою:</b> Середня")
            else:
                analytics.append("⚔️ <b>Майстерність бою:</b> Потребує тренування")
        except ValueError:
            analytics.append("⚔️ <b>Майстерність бою:</b> Дані потребують уточнення")
    
    # Аналіз командної гри
    teamfight = details.get('teamfight_participation_rate')
    if teamfight is not None:
        try:
            tf_num = float(str(teamfight).replace('%', ''))
            if tf_num >= 75:
                analytics.append("🤝 <b>Командна гра:</b> Відмінна участь у боях")
            elif tf_num >= 60:
                analytics.append("🤝 <b>Командна гра:</b> Хороша участь")
            else:
                analytics.append("🤝 <b>Командна гра:</b> Більше фокусуйтеся на команді")
        except ValueError:
            analytics.append("🤝 <b>Командна гра:</b> Дані потребують уточнення")
    
    if not analytics:
        analytics.append("📈 Аналітика недоступна через недостатність даних")
    
    return "\n".join(analytics)

async def _send_error_message(bot: Bot, chat_id: int, user_name: str, error_text: str) -> None:
    """Допоміжна функція для надсилання повідомлень про помилки."""
    try:
        await bot.send_message(chat_id, f"{error_text}, {user_name}. Спробуйте ще раз.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати повідомлення про помилку для {user_name}: {e}")

# === ОБРОБКА КОЛБЕКІВ (НАТИСКАННЯ КНОПОК) ===

async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None: 
    """
    Обробляє натискання кнопки "Аналіз".
    Викликає Vision API для аналізу зображення та надсилає результат користувачеві.
    
    Args:
        callback_query: Callback від натискання кнопки
        state: FSM контекст
        bot: Екземпляр бота
    """
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear()
        return

    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id 
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець") 
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt") 
    analysis_type = user_data.get("analysis_type")

    if not photo_file_id or not vision_prompt or not analysis_type:
        logger.error(f"Недостатньо даних у стані для аналізу для {user_name}")
        await _handle_analysis_error(callback_query, bot, chat_id, message_id, user_name, 
                                   "дані для аналізу втрачено або неповні")
        await state.clear()
        return

    # Оновлюємо UI - показуємо процес
    try:
        if callback_query.message.caption: 
            await callback_query.message.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {user_name}...",
                reply_markup=None 
            )
        else: 
            await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...") 
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name}: {e}")

    final_caption_text = f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."

    try:
        # Завантажуємо та обробляємо зображення
        file_info = await bot.get_file(photo_file_id) 
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")

        downloaded_file_io = await bot.download_file(file_info.file_path) 
        if downloaded_file_io is None: 
            raise ValueError("Не вдалося завантажити файл з Telegram для аналізу.")
        
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Викликаємо ШІ для аналізу
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer: 
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз ({analysis_type}) для {user_name}")
                
                # Генеруємо коментар від ШІ
                ai_comment = None
                if analysis_type == "profile":
                    ai_comment = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                    final_caption_text = format_profile_result(user_name, analysis_result_json, ai_comment)
                elif analysis_type == "player_stats":
                    # Поки що без коментаря для статистики, але можна додати пізніше
                    final_caption_text = format_player_stats_result(user_name, analysis_result_json, ai_comment)
                else:
                    logger.warning(f"Невідомий тип аналізу: {analysis_type} для {user_name}")
                    final_caption_text = f"Не вдалося обробити результати: невідомий тип аналізу, {user_name}."

            else:
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримано.'
                logger.error(f"Помилка аналізу ({analysis_type}) для {user_name}: {error_msg}")
                final_caption_text = await _format_error_response(user_name, error_msg, analysis_result_json)

    except TelegramAPIError as e:
        logger.exception(f"Telegram API помилка під час обробки файлу для {user_name}: {e}")
        final_caption_text = f"Пробач, {user_name}, виникла проблема з доступом до файлу скріншота в Telegram."
    except ValueError as e: 
        logger.exception(f"Помилка значення під час обробки файлу для {user_name}: {e}")
        final_caption_text = f"На жаль, {user_name}, не вдалося коректно обробити файл скріншота."
    except Exception as e: 
        logger.exception(f"Критична помилка обробки скріншота ({analysis_type}) для {user_name}: {e}")

    # Відображаємо результат
    await _display_analysis_result(bot, chat_id, message_id, final_caption_text, user_name)
    await state.clear()

async def _handle_analysis_error(callback_query: CallbackQuery, bot: Bot, chat_id: int, 
                               message_id: int, user_name: str, error_reason: str) -> None:
    """Обробляє помилки аналізу."""
    try:
        if callback_query.message and callback_query.message.caption:
            await callback_query.message.edit_caption(
                caption=f"Помилка, {user_name}: {error_reason}. Спробуйте надіслати скріншот ще раз."
            )
        else:
            await bot.send_message(chat_id, f"Помилка, {user_name}: {error_reason}. Спробуйте надіслати скріншот ще раз.")
    except TelegramAPIError:
        pass

async def _format_error_response(user_name: str, error_msg: str, analysis_result: Optional[Dict[str, Any]]) -> str:
    """Форматує повідомлення про помилку аналізу."""
    base_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
    
    if analysis_result and analysis_result.get("raw_response"):
        base_text += f"\nДеталі від ШІ: {html.escape(str(analysis_result.get('raw_response'))[:150])}..."
    elif analysis_result and analysis_result.get("details"):
        base_text += f"\nДеталі помилки: {html.escape(str(analysis_result.get('details'))[:150])}..."
    
    return base_text

async def _display_analysis_result(bot: Bot, chat_id: int, message_id: int, 
                                 result_text: str, user_name: str) -> None:
    """Відображає результат аналізу користувачеві."""
    try:
        # Видаляємо кнопки з оригінального повідомлення
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramAPIError as e:
            logger.warning(f"Не вдалося видалити кнопки з повідомлення для {user_name}: {e}")

        # Перевіряємо довжину тексту
        if len(result_text) > 1024:  # Telegram ліміт на підпис до фото
            logger.warning(f"Підпис до фото для {user_name} задовгий ({len(result_text)} символів).")
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption="")
            await send_message_in_chunks(bot, chat_id, result_text, ParseMode.HTML) 
        else:
            await bot.edit_message_caption( 
                chat_id=chat_id,
                message_id=message_id,
                caption=result_text,
                parse_mode=ParseMode.HTML
            )
        logger.info(f"Результати аналізу для {user_name} успішно відображено.")
        
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати повідомлення з результатами для {user_name}: {e}")
        try:
            await send_message_in_chunks(bot, chat_id, result_text, ParseMode.HTML) 
        except Exception as send_err:
            logger.error(f"Не вдалося надіслати результати аналізу для {user_name}: {send_err}")
            await _send_error_message(bot, chat_id, user_name, "сталася помилка при відображенні результатів аналізу")

async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    """ 
    Обробляє натискання кнопки "Видалити" на повідомленні-прев'ю скріншота.
    Видаляє повідомлення бота та очищає стан.
    
    Args:
        callback_query: Callback від натискання кнопки
        state: FSM контекст
    """
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
        else:
            logger.info(f"Повідомлення бота видалено користувачем (ID: {callback_query.from_user.id})")

    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота: {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)

# === ОБРОБКА СКАСУВАННЯ ТА НЕКОРЕКТНОГО ВВЕДЕННЯ ===

async def cancel_analysis(message: Message, state: FSMContext, bot: Bot) -> None: 
    """
    Обробник команди /cancel під час будь-якого етапу аналізу зображення.
    
    Args:
        message: Повідомлення з командою /cancel
        state: FSM контекст
        bot: Екземпляр бота
    """
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
    """
    Обробляє некоректне введення під час очікування скріншота або тригера аналізу.
    
    Args:
        message: Повідомлення від користувача
        state: FSM контекст
        bot: Екземпляр бота
        cmd_go_handler_func: Функція обробника команди /go
    """
    if not message.from_user: 
        return

    user_name_escaped = html.escape(message.from_user.first_name)
    user_id = message.from_user.id

    # Обробка /cancel
    if message.text and message.text.lower() == "/cancel":
        await cancel_analysis(message, state, bot) 
        return

    # Обробка /go - скасовуємо аналіз та виконуємо /go
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) ввів /go у стані аналізу.")
        await _cleanup_analysis_state(state, bot, message.chat.id if message.chat else None)
        await cmd_go_handler_func(message, state)
        return 

    # Обробка інших некоректних вводів
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

async def _cleanup_analysis_state(state: FSMContext, bot: Bot, chat_id: Optional[int]) -> None:
    """Очищає стан аналізу та видаляє пов'язані повідомлення."""
    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    
    if bot_message_id and chat_id:
        try: 
            await bot.delete_message(chat_id=chat_id, message_id=bot_message_id) 
        except TelegramAPIError: 
            pass
    
    await state.clear()

# === РЕЄСТРАЦІЯ ОБРОБНИКІВ ===

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None: 
    """
    Реєструє всі обробники, пов'язані з аналізом зображень.
    
    Args:
        dp: Диспетчер aiogram
        cmd_go_handler_func: Функція обробника команди /go
    """
    # Команди для запуску аналізу
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    dp.message.register(cmd_analyze_player_stats, Command("analyzestats"))

    # Обробка отримання фото
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    
    # Обробка натискання кнопок
    dp.callback_query.register(
        trigger_vision_analysis_callback, 
        F.data == "trigger_vision_analysis", 
        VisionAnalysisStates.awaiting_analysis_trigger
    )
    dp.callback_query.register(delete_bot_message_callback, F.data == "delete_bot_message")

    # Обробка команди /cancel для станів аналізу
    cancel_states = [
        VisionAnalysisStates.awaiting_profile_screenshot,
        VisionAnalysisStates.awaiting_analysis_trigger
    ]
    for cancel_state in cancel_states:
        dp.message.register(cancel_analysis, cancel_state, Command("cancel"))
    
    # Обробка некоректного вводу
    wrong_input_handler_with_go = lambda message, state, bot: handle_wrong_input_for_analysis(
        message, state, bot, cmd_go_handler_func
    )
    
    dp.message.register(wrong_input_handler_with_go, VisionAnalysisStates.awaiting_profile_screenshot)
    dp.message.register(wrong_input_handler_with_go, VisionAnalysisStates.awaiting_analysis_trigger)
    
    logger.info("Обробники аналізу зображень (профіль, статистика гравця) зареєстровано.")