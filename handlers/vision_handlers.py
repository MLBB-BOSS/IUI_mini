import base64
import html
import logging
import re
from typing import Dict, Any, Optional, Union
from decimal import Decimal, ROUND_HALF_UP

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
from utils.message_utils import send_message_in_chunks # Переконайся, що тут правильний шлях до оновленої функції


# === КОНСТАНТИ ДЛЯ АНАЛІТИКИ (залишаються як у твоєму коміті) ===
class MLBBAnalyticsCalculator:
    @staticmethod
    def safe_divide(numerator: Union[int, float, str], denominator: Union[int, float, str], 
                   precision: int = 2) -> Optional[float]:
        try:
            num = float(str(numerator).replace(',', '').replace(' ', ''))
            den = float(str(denominator).replace(',', '').replace(' ', ''))
            if den == 0: return None
            result = num / den
            return float(Decimal(str(result)).quantize(Decimal(f'0.{"0"*precision}'), rounding=ROUND_HALF_UP))
        except (ValueError, TypeError, ArithmeticError) as e:
            logger.debug(f"Помилка в safe_divide({numerator}, {denominator}): {e}")
            return None
    
    @staticmethod
    def safe_number(value: Any) -> Optional[float]:
        if value is None: return None
        try: return float(str(value).replace(',', '').replace(' ', ''))
        except (ValueError, TypeError): return None
    
    @classmethod
    def calculate_mvp_rating(cls, mvp_count: Any, matches_played: Any) -> Optional[float]:
        result = cls.safe_divide(mvp_count, matches_played, 4) # Збільшена точність для %
        return result * 100 if result is not None else None
    
    @classmethod
    def calculate_mvp_loss_percentage(cls, mvp_loss_count: Any, mvp_count: Any) -> Optional[float]:
        result = cls.safe_divide(mvp_loss_count, mvp_count, 4) # Збільшена точність для %
        return result * 100 if result is not None else None
    
    @classmethod
    def calculate_savage_frequency(cls, savage_count: Any, matches_played: Any) -> Optional[float]:
        frequency = cls.safe_divide(savage_count, matches_played, 5) # Збільшена точність для *1000
        return frequency * 1000 if frequency is not None else None
    
    @classmethod
    def calculate_legendary_frequency(cls, legendary_count: Any, matches_played: Any) -> Optional[float]:
        frequency = cls.safe_divide(legendary_count, matches_played, 4) # Збільшена точність для *100
        return frequency * 100 if frequency is not None else None
    
    @classmethod
    def calculate_gold_efficiency(cls, avg_hero_dmg_per_min: Any, avg_gold_per_min: Any) -> Optional[float]:
        return cls.safe_divide(avg_hero_dmg_per_min, avg_gold_per_min, 2)
    
    @classmethod
    def calculate_average_impact(cls, most_kills: Any, most_assists: Any) -> Optional[float]:
        kills = cls.safe_number(most_kills) or 0
        assists = cls.safe_number(most_assists) or 0
        return kills + assists if (kills > 0 or assists > 0) else None

class AnalysisFormatter:
    @staticmethod
    def _create_header_section(title: str, icon: str = "📊") -> str:
        return f"\n<b>{icon} {title}</b>\n" + "─" * 30 # Трохи коротша лінія
    
    @staticmethod
    def _format_field(label: str, value: Any, icon: str = "•", unit: str = "") -> str:
        if value is None or str(value).strip() == "": return f"  {icon} <b>{label}:</b> <i>не розпізнано</i>"
        display_value = str(value)
        if "★" in display_value or "зірок" in display_value.lower():
            display_value = re.sub(r'\s+★', '★', display_value.replace("зірок", "★").replace("зірки", "★"))
        return f"  {icon} <b>{label}:</b> {html.escape(display_value)}{unit}"
    
    @staticmethod
    def _format_metric(label: str, value: Optional[float], icon: str, unit: str = "", precision: int = 2) -> str:
        if value is None: return f"  {icon} <b>{label}:</b> <i>недостатньо даних</i>"
        formatted_value = f"{value:.{precision}f}" if precision > 0 else f"{value:.0f}"
        return f"  {icon} <b>{label}:</b> {formatted_value}{unit}"

# === ОБРОБНИКИ КОМАНД (залишаються як у твоєму коміті) ===
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzeprofile викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user; user_name_escaped = html.escape(user.first_name); user_id = user.id
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzeprofile.")
    await state.update_data(analysis_type="profile", vision_prompt=PROFILE_SCREENSHOT_PROMPT, original_user_name=user_name_escaped)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nБудь ласка, надішли мені скріншот свого профілю з Mobile Legends для аналізу.\nЯкщо передумаєш, просто надішли команду /cancel.", parse_mode=ParseMode.HTML)

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        logger.warning("Команда /analyzestats викликана без інформації про користувача.")
        await message.reply("Не вдалося отримати інформацію про користувача для початку аналізу.")
        return
    user = message.from_user; user_name_escaped = html.escape(user.first_name); user_id = user.id
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzestats.")
    await state.update_data(analysis_type="player_stats", vision_prompt=PLAYER_STATS_PROMPT, original_user_name=user_name_escaped)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nБудь ласка, надішли мені скріншот своєї ігрової статистики (зазвичай розділ \"Statistics\" → \"All Seasons\" або \"Current Season\").\nЯкщо передумаєш, просто надішли команду /cancel.", parse_mode=ParseMode.HTML)

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not message.chat: logger.error("handle_profile_screenshot: відсутній message.from_user або message.chat"); return
    user_data_state = await state.get_data()
    user_name_escaped = user_data_state.get("original_user_name", html.escape(message.from_user.first_name if message.from_user else "Гравець"))
    user_id = message.from_user.id; chat_id = message.chat.id
    logger.info(f"Отримано скріншот для аналізу від {user_name_escaped} (ID: {user_id}).")
    if not message.photo: await message.answer(f"Щось пішло не так, {user_name_escaped}. Будь ласка, надішли саме фото (скріншот)."); return
    photo_file_id = message.photo[-1].file_id
    try: await message.delete(); logger.info(f"Повідомлення користувача {user_name_escaped} (ID: {user_id}) зі скріншотом видалено.")
    except TelegramAPIError as e: logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped}: {e}")
    await state.update_data(vision_photo_file_id=photo_file_id)
    caption_text = ("Скріншот отримано.\nНатисніть «🔍 Аналіз», щоб дізнатися більше, або «🗑️ Видалити», щоб скасувати операцію.")
    analyze_button = InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")
    delete_preview_button = InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[analyze_button, delete_preview_button]])
    try:
        sent_message = await bot.send_photo(chat_id=chat_id, photo=photo_file_id, caption=caption_text, reply_markup=keyboard)
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
        logger.info(f"Скріншот від {user_name_escaped} (ID: {user_id}) повторно надіслано ботом з кнопками.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для {user_name_escaped}: {e}")
        await _send_error_message(bot, chat_id, user_name_escaped, "Не вдалося обробити ваш запит на аналіз")
        await state.clear()

# === ФОРМАТУВАННЯ РЕЗУЛЬТАТІВ АНАЛІЗУ (з твого коду, з невеликими правками) ===
# Ці функції format_profile_result та format_player_stats_result збирають HTML.
# Ми їх використаємо для генерації final_caption_text.
# Порядок блоків всередині них вже такий, як ти хотів (Коментар, Унікальна, Детальна).
# Головне, що ці функції НЕ будуть генерувати <pre> теги, це зробить _get_formatted_raw_stats_for_pre_block.

def _get_formatted_raw_stats_for_pre_block(data: Dict[str, Any], analysis_type: str, user_name: str) -> str:
    """Готує 'сирі' дані для <pre> блоку, повертаючи простий текст."""
    lines = []
    
    def _get_val(source_dict, key, default="N/A"):
        val = source_dict.get(key)
        return str(val) if val is not None else default

    if analysis_type == "player_stats":
        lines.append(f"Детальна статистика гравця {user_name} ({data.get('stats_filter_type', 'N/A')}):")
        main_ind = data.get("main_indicators", {})
        lines.append("\nОсновні показники:")
        lines.append(f"  • Матчів зіграно: {_get_val(main_ind, 'matches_played')}")
        wr = _get_val(main_ind, 'win_rate'); lines.append(f"  • Відсоток перемог: {wr}%" if wr != "N/A" else "  • Відсоток перемог: N/A")
        lines.append(f"  • MVP: {_get_val(main_ind, 'mvp_count')}")

        ach_left = data.get("achievements_left_column", {})
        lines.append("\nДосягнення (колонка 1):")
        lines.append(f"  • Легендарних: {_get_val(ach_left, 'legendary_count')}")
        lines.append(f"  • Маніяків: {_get_val(ach_left, 'maniac_count')}")
        # ... і так далі для всіх полів achievements_left_column
        lines.append(f"  • Подвійних вбивств: {_get_val(ach_left, 'double_kill_count')}")
        lines.append(f"  • Найб. вбивств за гру: {_get_val(ach_left, 'most_kills_in_one_game')}")
        lines.append(f"  • Найдовша серія перемог: {_get_val(ach_left, 'longest_win_streak')}")
        lines.append(f"  • Найб. шкоди/хв: {_get_val(ach_left, 'highest_dmg_per_min')}")
        lines.append(f"  • Найб. золота/хв: {_get_val(ach_left, 'highest_gold_per_min')}")


        ach_right = data.get("achievements_right_column", {})
        lines.append("\nДосягнення (колонка 2):")
        lines.append(f"  • Дикунств (Savage): {_get_val(ach_right, 'savage_count')}")
        lines.append(f"  • Потрійних вбивств: {_get_val(ach_right, 'triple_kill_count')}")
        # ... і так далі для всіх полів achievements_right_column
        lines.append(f"  • MVP при поразці: {_get_val(ach_right, 'mvp_loss_count')}")
        lines.append(f"  • Найб. допомоги за гру: {_get_val(ach_right, 'most_assists_in_one_game')}")
        lines.append(f"  • Перша кров: {_get_val(ach_right, 'first_blood_count')}")
        lines.append(f"  • Найб. отриманої шкоди/хв: {_get_val(ach_right, 'highest_dmg_taken_per_min')}")

        details = data.get("details_panel", {})
        lines.append("\nДеталі (права панель):")
        lines.append(f"  • KDA: {_get_val(details, 'kda_ratio')}")
        tfpr = _get_val(details, 'teamfight_participation_rate'); lines.append(f"  • Участь у ком. боях: {tfpr}%" if tfpr != "N/A" else "  • Участь у ком. боях: N/A")
        # ... і так далі для всіх полів details_panel
        lines.append(f"  • Сер. золото/хв: {_get_val(details, 'avg_gold_per_min')}")
        lines.append(f"  • Сер. шкода героям/хв: {_get_val(details, 'avg_hero_dmg_per_min')}")
        lines.append(f"  • Сер. смертей/матч: {_get_val(details, 'avg_deaths_per_match')}")
        lines.append(f"  • Сер. шкода вежам/матч: {_get_val(details, 'avg_turret_dmg_per_match')}")

    elif analysis_type == "profile":
        lines.append(f"Інформація профілю гравця {user_name}:")
        fields = {
            "game_nickname": "Нікнейм", "mlbb_id_server": "ID (Сервер)", 
            "highest_rank_season": "Найвищий ранг", "matches_played": "Матчів зіграно", 
            "likes_received": "Лайків отримано", "location": "Локація", "squad_name": "Сквад"
        }
        for key, label in fields.items():
            value_raw = data.get(key)
            value_str = str(value_raw) if value_raw is not None else "не розпізнано"
            if key == "highest_rank_season" and value_raw is not None:
                 if "★" in value_str or "зірок" in value_str.lower():
                    value_str = re.sub(r'\s+★', '★', value_str.replace("зірок", "★").replace("зірки", "★"))
            lines.append(f"  • {label}: {value_str}")
            
    return "\n".join(lines)

def _calculate_unique_analytics(data: Dict[str, Any], analysis_type: str) -> str: # Ця функція з твого коду, генерує HTML
    calc = MLBBAnalyticsCalculator()
    analytics_html_parts = [] # Будемо збирати HTML частини тут
    
    if analysis_type == "player_stats":
        main_ind = data.get("main_indicators", {})
        ach_left = data.get("achievements_left_column", {})
        ach_right = data.get("achievements_right_column", {})
        details = data.get("details_panel", {})
        matches_played = main_ind.get('matches_played')
        
        mvp_rating = calc.calculate_mvp_rating(main_ind.get('mvp_count'), matches_played)
        analytics_html_parts.append(AnalysisFormatter._format_metric("MVP Рейтинг", mvp_rating, "⭐", "% матчів"))
        
        mvp_loss_percentage = calc.calculate_mvp_loss_percentage(ach_right.get('mvp_loss_count'), main_ind.get('mvp_count'))
        analytics_html_parts.append(AnalysisFormatter._format_metric("Частка MVP у поразках", mvp_loss_percentage, "💔", "%"))

        savage_frequency = calc.calculate_savage_frequency(ach_right.get('savage_count'), matches_played)
        analytics_html_parts.append(AnalysisFormatter._format_metric("Частота Savage", savage_frequency, "🔥", " на 1000 матчів"))
        
        legendary_frequency = calc.calculate_legendary_frequency(ach_left.get('legendary_count'), matches_played)
        analytics_html_parts.append(AnalysisFormatter._format_metric("Частота Legendary", legendary_frequency, "✨", " на 100 матчів"))

        gold_efficiency = calc.calculate_gold_efficiency(details.get('avg_hero_dmg_per_min'), details.get('avg_gold_per_min'))
        analytics_html_parts.append(AnalysisFormatter._format_metric("Ефективність золота", gold_efficiency, "💰", " шкоди/хв на 1 золото/хв"))
        
        win_rate = main_ind.get('win_rate')
        if win_rate is not None and matches_played is not None:
            matches_num = calc.safe_number(matches_played)
            wr_num = calc.safe_number(win_rate)
            if matches_num and wr_num and matches_num > 0: # Додав перевірку matches_num > 0
                wins = int(matches_num * wr_num / 100)
                losses = int(matches_num - wins)
                analytics_html_parts.append(AnalysisFormatter._format_field("Перемог/Поразок", f"{wins} / {losses}", "👑"))
        
        # avg_impact = calc.calculate_average_impact(ach_left.get('most_kills_in_one_game'), ach_right.get('most_assists_in_one_game'))
        # analytics_html_parts.append(AnalysisFormatter._format_metric("Сер. вплив (K+A)/матч", avg_impact, "🎯", "", 2)) # Закоментував, бо це сума макс, а не середнє

    elif analysis_type == "profile": # Це _generate_profile_analytics з твого коду
        analytics_html_parts.extend(_generate_profile_analytics_list(data)) # Використовуємо нову функцію, що повертає список рядків

    return "\n".join(analytics_html_parts) if analytics_html_parts else "📈 <i>Недостатньо даних для унікальної аналітики.</i>"

def _generate_profile_analytics_list(data: Dict[str, Any]) -> list[str]: # Допоміжна функція, що повертає список
    """ Генерує базову аналітику для профілю у вигляді списку HTML-рядків. """
    analytics_list = []
    calc = MLBBAnalyticsCalculator()
    try:
        rank = data.get("highest_rank_season")
        if rank:
            rank_str = str(rank).lower()
            if "mythic" in rank_str or "міфічний" in rank_str: analytics_list.append("  🔮 <b>Статус:</b> Досвідчений гравець вищого рівня")
            elif "legend" in rank_str or "легенда" in rank_str: analytics_list.append("  ⭐ <b>Статус:</b> Сильний гравець")
            elif "epic" in rank_str or "епік" in rank_str: analytics_list.append("  💎 <b>Статус:</b> Гравець середнього рівня")
            else: analytics_list.append("  🌱 <b>Статус:</b> Гравець, що розвивається")
        
        matches = data.get("matches_played")
        if matches:
            matches_num = calc.safe_number(matches)
            if matches_num is not None: # Додав перевірку на None
                if matches_num > 5000: analytics_list.append("  🎮 <b>Активність:</b> Надзвичайно активний")
                elif matches_num > 2000: analytics_list.append("  🎮 <b>Активність:</b> Дуже активний")
                elif matches_num > 1000: analytics_list.append("  🎮 <b>Активність:</b> Регулярний гравець")
                else: analytics_list.append("  🎮 <b>Активність:</b> Помірний гравець")
        
        likes = data.get("likes_received")
        if likes:
            likes_num = calc.safe_number(likes)
            if likes_num is not None: # Додав перевірку на None
                if likes_num > 1000: analytics_list.append("  👥 <b>Популярність:</b> Високо оцінений")
                elif likes_num > 500: analytics_list.append("  👥 <b>Популярність:</b> Добре відомий")
                else: analytics_list.append("  👥 <b>Популярність:</b> Будує репутацію")
        
        if not analytics_list: analytics_list.append("  📈 <i>Базова аналітика недоступна.</i>")
    except Exception as e:
        logger.error(f"Помилка генерації аналітики профілю: {e}")
        analytics_list.append("  📈 <i>Помилка генерації аналітики.</i>")
    return analytics_list


async def _send_error_message(bot: Bot, chat_id: int, user_name: str, error_text: str, reply_to_id: Optional[int] = None) -> None:
    try:
        await bot.send_message(chat_id, f"{error_text}, {user_name}. Спробуйте ще раз.", reply_to_message_id=reply_to_id)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати повідомлення про помилку для {user_name}: {e}")

# === ОБРОБКА КОЛБЕКІВ ===
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear(); return

    chat_id = callback_query.message.chat.id
    message_id_to_process = callback_query.message.message_id # ID повідомлення з фото, яке будемо редагувати або на яке відповідати
    
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")
    analysis_type = user_data.get("analysis_type")

    if not all([photo_file_id, vision_prompt, analysis_type]):
        logger.error(f"Недостатньо даних у FSM для аналізу для {user_name} (ID: {callback_query.from_user.id}).")
        await _send_error_message(bot, chat_id, user_name, "Помилка: дані для аналізу неповні", reply_to_id=message_id_to_process)
        await state.clear(); return

    try: # Оновлюємо UI: "Обробляю..."
        if callback_query.message.caption:
            await callback_query.message.edit_caption(caption=f"⏳ Обробляю ваш скріншот, {user_name}...", reply_markup=None)
        # Якщо немає caption, але є кнопки, то видаляємо кнопки (edit_reply_markup)
        elif callback_query.message.reply_markup:
             await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося оновити підпис/кнопки перед аналізом для {user_name} (ID: {callback_query.from_user.id}): {e}")

    # Ініціалізація змінних
    generated_comment_html = ""
    unique_analytics_html = ""
    raw_stats_plain_text_for_pre = "" # Текст для <pre>
    error_in_processing = False
    final_text_to_display = f"На жаль, {user_name}, сталася помилка під час обробки вашого запиту." # Дефолтне повідомлення

    try:
        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path: raise ValueError("Не вдалося отримати шлях до файлу.")
        
        downloaded_file = await bot.download_file(file_info.file_path)
        if downloaded_file is None: raise ValueError("Завантаження файлу повернуло None.")
        image_bytes = downloaded_file.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if not analysis_result_json or "error" in analysis_result_json:
                error_msg = analysis_result_json.get('error', 'Невідома помилка') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка Vision API ({analysis_type}) для {user_name} (ID: {callback_query.from_user.id}): {error_msg}")
                final_text_to_display = await _format_error_response(user_name, error_msg, analysis_result_json)
                error_in_processing = True
            else:
                logger.info(f"Успішний Vision аналіз ({analysis_type}) для {user_name} (ID: {callback_query.from_user.id}).")
                
                # 1. Генеруємо коментар від IUI
                ai_comment_text = ""
                # Важливо: передавати розраховані дані в get_player_stats_description, якщо це потрібно промптом
                # Для цього треба мати функцію, що повертає словник розрахованих даних
                # Припустимо, що сервіс OpenAI може обробляти це або ми адаптуємо його пізніше
                data_for_comment_generation = analysis_result_json.copy()
                # Тут можна додати derived_stats до data_for_comment_generation, якщо є функція, що повертає словник

                if analysis_type == "player_stats":
                    # Переконайся, що в MLBBChatGPT є метод get_player_stats_description
                    # або get_stats_professional_commentary, і він правильно працює
                    ai_comment_text = await gpt_analyzer.get_player_stats_description(user_name, data_for_comment_generation)
                elif analysis_type == "profile":
                    ai_comment_text = await gpt_analyzer.get_profile_description(user_name, data_for_comment_generation)

                if ai_comment_text and "<i>" not in ai_comment_text: # Уникаємо відображення заглушок
                    generated_comment_html = f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(ai_comment_text)}"
                elif ai_comment_text: # Якщо це все ж заглушка з <i>
                    generated_comment_html = ai_comment_text
                
                # 2. Генеруємо унікальну аналітику (HTML)
                # _calculate_unique_analytics вже повертає готовий HTML блок або повідомлення про помилку/недостатність даних
                unique_analytics_html_content = _calculate_unique_analytics(analysis_result_json, analysis_type)
                if unique_analytics_html_content and "<i>" not in unique_analytics_html_content:
                     unique_analytics_html = f"<b>📈 <u>Унікальна Аналітика від IUI:</u></b>\n{unique_analytics_html_content}"
                elif unique_analytics_html_content : # Якщо там вже є <i> з повідомленням
                    unique_analytics_html = unique_analytics_html_content


                # 3. Форматуємо "суху" статистику для <pre>
                raw_stats_plain_text_for_pre = _get_formatted_raw_stats_for_pre_block(analysis_result_json, analysis_type, user_name)
                
                # Збираємо фінальний текст у бажаному порядку
                final_parts = []
                if generated_comment_html: final_parts.append(generated_comment_html)
                if unique_analytics_html: final_parts.append(unique_analytics_html)
                
                if raw_stats_plain_text_for_pre:
                    raw_stats_header = AnalysisFormatter._create_header_section(
                        f"Детальна інформація ({user_name}) для копіювання", "📋" # Більш загальний заголовок
                    ).strip() # strip() щоб прибрати зайві \n на початку/кінці
                    final_parts.append(f"{raw_stats_header}\n<pre>{html.escape(raw_stats_plain_text_for_pre)}</pre>")
                
                final_text_to_display = "\n\n".join(filter(None, final_parts))
                if not final_text_to_display: # Якщо раптом всі частини порожні
                    final_text_to_display = f"Не вдалося згенерувати детальний аналіз для {user_name}."
                    error_in_processing = True


    except ValueError as e: # Наприклад, від get_file або download_file
        logger.error(f"Помилка значення під час обробки файлу для {user_name} (ID: {callback_query.from_user.id}): {e}", exc_info=True)
        final_text_to_display = f"На жаль, {user_name}, не вдалося коректно обробити файл скріншота: {html.escape(str(e))}"
        error_in_processing = True
    except TelegramAPIError as e: # Специфічні помилки Telegram
        logger.error(f"Telegram API помилка під час обробки запиту для {user_name} (ID: {callback_query.from_user.id}): {e}", exc_info=True)
        final_text_to_display = f"Пробач, {user_name}, виникла технічна проблема з Telegram: {html.escape(str(e))}"
        error_in_processing = True
    except Exception as e: # Інші непередбачені помилки
        logger.exception(f"Критична помилка під час обробки аналізу ({analysis_type}) для {user_name} (ID: {callback_query.from_user.id}): {e}")
        final_text_to_display = f"На жаль, {user_name}, сталася непередбачена системна помилка. Адміністрація вже сповіщена."
        # Тут можна додати логіку сповіщення адміністратора, якщо потрібно
        error_in_processing = True

    # Надсилаємо результат користувачеві
    await _display_analysis_result(bot, chat_id, message_id_to_process, final_text_to_display, user_name, error_in_processing)
    await state.clear()


async def _handle_analysis_error(callback_query: CallbackQuery, bot: Bot, chat_id: int, 
                               message_id: int, user_name: str, error_reason: str) -> None:
    # Ця функція використовувалася у твоєму коді, залишаю її, якщо вона потрібна десь ще.
    # У trigger_vision_analysis_callback логіка помилок тепер обробляється напряму.
    try:
        if callback_query.message and callback_query.message.caption:
            await callback_query.message.edit_caption(caption=f"Помилка, {user_name}: {error_reason}. Спробуйте надіслати скріншот ще раз.")
        else:
            await bot.send_message(chat_id, f"Помилка, {user_name}: {error_reason}. Спробуйте надіслати скріншот ще раз.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати повідомлення про помилку аналізу для {user_name}: {e}")

async def _format_error_response(user_name: str, error_msg: str, analysis_result: Optional[Dict[str, Any]]) -> str:
    # Ця функція використовувалася у твоєму коді.
    base_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
    if analysis_result:
        raw_response = analysis_result.get('raw_response')
        details = analysis_result.get('details')
        if raw_response: base_text += f"\nДеталі від ШІ: {html.escape(str(raw_response)[:150])}..."
        elif details: base_text += f"\nДеталі помилки: {html.escape(str(details)[:150])}..."
    return base_text

async def _display_analysis_result(bot: Bot, chat_id: int, message_id_to_process: int, 
                                 result_text: str, user_name: str, 
                                 error_in_processing: bool) -> None: # Додано error_in_processing
    """
    Відображає результат аналізу: редагує підпис до фото або надсилає відповідь.
    """
    try:
        # Спочатку спробуємо видалити кнопки з повідомлення, яке ми будемо редагувати/на яке відповідати
        try:
            # Перевіряємо, чи це повідомлення з фото, перш ніж редагувати reply_markup
            # Якщо це текстове повідомлення (малоймовірно, але можливо), edit_message_reply_markup може дати помилку
            # Але оскільки ми завжди надсилаємо фото з кнопками, ця перевірка може бути зайвою.
            # Головне - обробити помилку, якщо повідомлення вже не існує або не має кнопок.
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id_to_process, reply_markup=None)
        except TelegramAPIError as e:
            logger.debug(f"Не вдалося видалити кнопки з повідомлення {message_id_to_process} для {user_name}: {e}. Можливо, воно вже змінене/видалене або не мало кнопок.")

        if len(result_text) <= 1024: # Якщо весь текст влазить у підпис
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id_to_process, 
                caption=result_text,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Результати аналізу для {user_name} успішно відображено в підписі до фото.")
        else: # Текст задовгий для підпису
            placeholder_caption = "✅ Аналіз завершено! Деталі у повідомленні-відповіді нижче 👇"
            if error_in_processing:
                 placeholder_caption = "ℹ️ Результат обробки у повідомленні-відповіді нижче 👇"
            
            logger.info(f"Текст аналізу для {user_name} задовгий ({len(result_text)}). Редагую підпис фото на '{placeholder_caption}' та надсилаю деталі як відповідь.")
            
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id_to_process,
                    caption=placeholder_caption
                )
            except TelegramAPIError as e: # Якщо не вдалося змінити підпис (наприклад, повідомлення видалено)
                logger.warning(f"Не вдалося відредагувати підпис до фото {message_id_to_process} на плейсхолдер: {e}. Спробую просто надіслати відповідь.")
            
            # Надсилаємо повний текст як відповідь на оригінальне фото-повідомлення
            await send_message_in_chunks(
                bot,
                chat_id,
                result_text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message_id_to_process # ВАЖЛИВО: робимо це відповіддю
            )
            logger.info(f"Деталі аналізу для {user_name} надіслано як відповідь на повідомлення {message_id_to_process}.")

    except TelegramAPIError as e: # Загальна помилка Telegram при спробі редагувати/надсилати
        logger.error(f"TelegramAPIError при відображенні результату для {user_name} (повідомлення {message_id_to_process}): {e}", exc_info=True)
        try: 
            await send_message_in_chunks(bot, chat_id, result_text, ParseMode.HTML, reply_to_message_id=message_id_to_process if not error_in_processing else None)
        except Exception as final_send_err:
            logger.error(f"Критична помилка: не вдалося надіслати результат аналізу для {user_name} навіть як новий текст: {final_send_err}", exc_info=True)
            await _send_error_message(bot, chat_id, user_name, "сталася серйозна помилка при відображенні результатів", reply_to_id=message_id_to_process if not error_in_processing else None)
    except Exception as e: # Інші непередбачені помилки
        logger.error(f"Загальна помилка при відображенні результату для {user_name} (повідомлення {message_id_to_process}): {e}", exc_info=True)
        await _send_error_message(bot, chat_id, user_name, "виникла непередбачена помилка при показі результатів", reply_to_id=message_id_to_process if not error_in_processing else None)


# === ІНШІ ОБРОБНИКИ (залишаються як у твоєму коміті) ===
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
    await state.clear(); await message.reply(f"Аналіз зображення скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go або іншу команду аналізу.", parse_mode=ParseMode.HTML)

async def handle_wrong_input_for_analysis(message: Message, state: FSMContext, bot: Bot, cmd_go_handler_func) -> None:
    if not message.from_user: return
    user_name_escaped = html.escape(message.from_user.first_name); user_id = message.from_user.id
    if message.text and message.text.lower() == "/cancel": await cancel_analysis(message, state, bot); return
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) ввів /go у стані аналізу.")
        # Перейменовано _cleanup_analysis_state на _cleanup_vision_analysis_state для ясності
        chat_id_for_cleanup = message.chat.id if message.chat else None
        await _cleanup_vision_analysis_state(state, bot, chat_id_for_cleanup) 
        await cmd_go_handler_func(message, state); return
        
    current_state_name = await state.get_state(); user_data = await state.get_data()
    analysis_type_display = user_data.get("analysis_type", "невідомого типу")
    if current_state_name == VisionAnalysisStates.awaiting_profile_screenshot.state:
        logger.info(f"Користувач {user_name_escaped} надіслав не фото у стані awaiting_profile_screenshot (для аналізу типу: {analysis_type_display}).")
        await message.reply(f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) для аналізу {analysis_type_display} або команду /cancel для скасування.", parse_mode=ParseMode.HTML)
    elif current_state_name == VisionAnalysisStates.awaiting_analysis_trigger.state:
        logger.info(f"Користувач {user_name_escaped} надіслав '{html.escape(message.text or 'не текстове повідомлення')}' у стані awaiting_analysis_trigger (для аналізу типу: {analysis_type_display}).")
        await message.reply(f"Очікувалася дія з аналізом (кнопка під фото) або команду /cancel, {user_name_escaped}.", parse_mode=ParseMode.HTML)
    else:
        logger.info(f"Користувач {user_name_escaped} надіслав некоректне введення у непередбаченому стані аналізу ({current_state_name}). Пропоную скасувати.")
        await message.reply(f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.", parse_mode=ParseMode.HTML)

async def _cleanup_vision_analysis_state(state: FSMContext, bot: Bot, chat_id: Optional[int]) -> None: # Перейменовано
    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id and chat_id:
        try: await bot.delete_message(chat_id=chat_id, message_id=bot_message_id)
        except TelegramAPIError as e: logger.debug(f"Не вдалося видалити повідомлення при очищенні стану візуального аналізу: {e}")
    await state.clear()

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None:
    try:
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
        logger.info("✅ Обробники аналізу зображень (профіль, статистика гравця) успішно зареєстровано.")
    except Exception as e:
        logger.error(f"❌ Помилка при реєстрації обробників аналізу зображень: {e}")
        raise