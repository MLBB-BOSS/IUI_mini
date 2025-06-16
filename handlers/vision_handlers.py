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

# Імпорти з проєкту (вкажіть ваші модулі)
from config import OPENAI_API_KEY, logger
from services.openai_service import (
    MLBBChatGPT, 
    PROFILE_SCREENSHOT_PROMPT, 
    PLAYER_STATS_PROMPT
)
from states.vision_states import VisionAnalysisStates
from utils.message_utils import send_message_in_chunks

# Локалізовані шаблони коментарів українською
COMMENT_TEMPLATES = {
    "high_win_rate": "Вау, {user}, твій win rate — як у справжнього чемпіона! 🏆 Продовжуй так!",
    "low_kda": "Гей, {user}, трохи більше обережності, і твій KDA засяє! 😎",
    "high_mvp_rate": "Ти часто MVP, {user}! 🥇 Команда точно цінує твої навички!",
    "rare_savage": "Savage кожні {n} матчів, {user}? Ти справжній хижак на арені! 🐺"
}

class MLBBAnalyticsCalculator:
    """Клас для обчислення унікальних метрик аналітики."""
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

    @classmethod
    def calculate_mvp_rating(cls, mvp_count: Any, matches_played: Any) -> Optional[float]:
        result = cls.safe_divide(mvp_count, matches_played, 2)
        return result * 100 if result is not None else None

    @classmethod
    def calculate_savage_frequency(cls, savage_count: Any, matches_played: Any) -> Optional[float]:
        frequency = cls.safe_divide(savage_count, matches_played)
        return frequency * 1000 if frequency is not None else None

    @classmethod
    def calculate_damage_per_gold_ratio(cls, avg_hero_dmg_per_min: Any, avg_gold_per_min: Any) -> Optional[float]:
        return cls.safe_divide(avg_hero_dmg_per_min, avg_gold_per_min, 2)

    @classmethod
    def calculate_avg_impact_score(cls, kda_ratio: Any, avg_deaths_per_match: Any) -> Optional[float]:
        kda = cls.safe_number(kda_ratio)
        deaths = cls.safe_number(avg_deaths_per_match)
        if kda is not None and deaths is not None:
            return kda * deaths if deaths > 0 else kda
        return None

class AnalysisFormatter:
    """Клас для форматування результатів аналітики."""
    @staticmethod
    def _create_header_section(title: str, icon: str = "📊") -> str:
        return f"\n<b>{icon} {title}</b>\n" + "─" * 35

    @staticmethod
    def _format_field(label: str, value: Any, icon: str = "•", unit: str = "") -> str:
        if value is None or value == "":
            return f"  {icon} <b>{label}:</b> <i>не розпізнано</i>"
        display_value = str(value)
        if "★" in display_value or "зірок" in display_value.lower():
            display_value = re.sub(r'\s+★', '★', display_value.replace("зірок", "★").replace("зірки", "★"))
        return f"  {icon} <b>{label}:</b> {html.escape(display_value)}{unit}"

    @staticmethod
    def _format_metric(label: str, value: Optional[float], icon: str, unit: str = "", precision: int = 2) -> str:
        if value is None:
            return f"  {icon} <b>{label}:</b> <i>недостатньо даних</i>"
        formatted_value = f"{value:.{precision}f}" if precision > 0 else f"{value:.0f}"
        return f"  {icon} <b>{label}:</b> {formatted_value}{unit}"

# Обробники команд
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    """Команда для аналізу профілю."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    await state.update_data(analysis_type="profile", vision_prompt=PROFILE_SCREENSHOT_PROMPT, original_user_name=user_name_escaped)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНадішли скріншот профілю з Mobile Legends.")

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    """Команда для аналізу статистики гравця."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name)
    await state.update_data(analysis_type="player_stats", vision_prompt=PLAYER_STATS_PROMPT, original_user_name=user_name_escaped)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНадішли скріншот статистики (\"Statistics\" → \"All Seasons\").")

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обробка надісланого скріншоту."""
    user_data_state = await state.get_data()
    user_name_escaped = user_data_state.get("original_user_name", html.escape(message.from_user.first_name))
    if not message.photo:
        await message.answer(f"Надішли фото, {user_name_escaped}.")
        return
    photo_file_id = message.photo[-1].file_id
    await message.delete()
    await state.update_data(vision_photo_file_id=photo_file_id)
    caption_text = "Скріншот отримано.\nВиберіть дію:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis"),
         InlineKeyboardButton(text="📊 Короткий огляд", callback_data="quick_overview"),
         InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")]
    ])
    sent_message = await bot.send_photo(chat_id=message.chat.id, photo=photo_file_id, caption=caption_text, reply_markup=keyboard)
    await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
    await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)

def format_profile_result(user_name: str, data: Dict[str, Any], ai_comment: Optional[str] = None) -> str:
    """Форматування результатів аналізу профілю."""
    parts = []
    if ai_comment:
        parts.append(AnalysisFormatter._create_header_section("Коментар від IUI", "🎙️"))
        parts.append(html.escape(ai_comment))
    parts.append(AnalysisFormatter._create_header_section("Унікальна Аналітика", "📈"))
    parts.append(_generate_profile_analytics(data))
    parts.append(AnalysisFormatter._create_header_section("Детальна статистика", "📊"))
    fields = {
        "game_nickname": "🎮 Нікнейм",
        "mlbb_id_server": "🆔 ID (Сервер)",
        "highest_rank_season": "🌟 Найвищий ранг",
        "matches_played": "⚔️ Матчів зіграно",
        "likes_received": "👍 Лайків отримано",
        "location": "🌍 Локація",
        "squad_name": "🛡️ Сквад"
    }
    for key, label in fields.items():
        value = data.get(key)
        parts.append(AnalysisFormatter._format_field(label, value, ""))
    return "\n".join(parts)

def format_player_stats_result(user_name: str, data: Dict[str, Any], ai_comment: Optional[str] = None) -> str:
    """Форматування результатів аналізу статистики."""
    parts = []
    if ai_comment:
        parts.append(AnalysisFormatter._create_header_section("Коментар від IUI", "🎙️"))
        parts.append(html.escape(ai_comment))
    parts.append(AnalysisFormatter._create_header_section("Унікальна Аналітика", "📈"))
    parts.append(_calculate_unique_analytics(data))
    parts.append(AnalysisFormatter._create_header_section("Детальна статистика", "📊"))
    parts.append(_format_raw_stats(data))
    parts.append("\n<b>📋 Для копіювання:</b>\n<pre>{}</pre>".format(html.escape(_format_raw_stats_text(data))))
    return "\n".join(parts)

def _calculate_unique_analytics(data: Dict[str, Any]) -> str:
    """Обчислення унікальної аналітики для статистики."""
    calc = MLBBAnalyticsCalculator()
    analytics = []
    main_ind = data.get("main_indicators", {})
    details = data.get("details_panel", {})
    ach_left = data.get("achievements_left_column", {})
    ach_right = data.get("achievements_right_column", {})

    damage_per_gold = calc.calculate_damage_per_gold_ratio(details.get('avg_hero_dmg_per_min'), details.get('avg_gold_per_min'))
    analytics.append(AnalysisFormatter._format_metric("Ефективність золота", damage_per_gold, "⚡", " шкоди/хв на 1 золото/хв"))

    impact_score = calc.calculate_avg_impact_score(details.get('kda_ratio'), details.get('avg_deaths_per_match'))
    analytics.append(AnalysisFormatter._format_metric("Сер. вплив (KDA*смерті)", impact_score, "🎯", "", 2))

    mvp_rating = calc.calculate_mvp_rating(main_ind.get('mvp_count'), main_ind.get('matches_played'))
    analytics.append(AnalysisFormatter._format_metric("MVP Рейтинг", mvp_rating, "⭐", "% матчів"))

    savage_freq = calc.calculate_savage_frequency(ach_right.get('savage_count'), main_ind.get('matches_played'))
    analytics.append(AnalysisFormatter._format_metric("Частота Savage", savage_freq, "🔥", " на 1000 матчів", 2))

    return "\n".join(analytics) or "📈 Недостатньо даних"

def _generate_profile_analytics(data: Dict[str, Any]) -> str:
    """Генерація аналітики для профілю."""
    analytics = []
    rank = data.get("highest_rank_season")
    if rank:
        rank_str = str(rank).lower()
        if "mythic" in rank_str:
            analytics.append("🔮 <b>Статус:</b> Досвідчений гравець вищого рівня")
        elif "legend" in rank_str:
            analytics.append("⭐ <b>Статус:</b> Сильний гравець з хорошими навичками")
    matches = data.get("matches_played")
    if matches:
        matches_num = MLBBAnalyticsCalculator.safe_number(matches)
        if matches_num > 2000:
            analytics.append("🎮 <b>Активність:</b> Дуже активний гравець")
    return "\n".join(analytics) or "📈 Базова аналітика недоступна"

def _format_raw_stats(data: Dict[str, Any]) -> str:
    """Форматування сирої статистики в HTML."""
    parts = []
    main_ind = data.get("main_indicators", {})
    parts.append(AnalysisFormatter._format_field("Матчів зіграно", main_ind.get('matches_played'), "🎯"))
    win_rate = main_ind.get('win_rate')
    if win_rate is not None:
        parts.append(AnalysisFormatter._format_field("Відсоток перемог", f"{win_rate}%", "🏆"))
    parts.append(AnalysisFormatter._format_field("MVP", main_ind.get('mvp_count'), "👑"))
    return "\n".join(parts)

def _format_raw_stats_text(data: Dict[str, Any]) -> str:
    """Форматування сирої статистики для копіювання."""
    lines = [f"Детальна статистика:"]
    main_ind = data.get("main_indicators", {})
    lines.append(f"Матчів зіграно: {main_ind.get('matches_played', 'N/A')}")
    lines.append(f"Відсоток перемог: {main_ind.get('win_rate', 'N/A')}%")
    lines.append(f"MVP: {main_ind.get('mvp_count', 'N/A')}")
    return "\n".join(lines)

async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Обробка натискання кнопки 'Аналіз'."""
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")
    analysis_type = user_data.get("analysis_type")
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")

    async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
        analysis_result_json = await gpt_analyzer.analyze_image_with_vision(photo_file_id, vision_prompt)
        if analysis_type == "profile":
            ai_comment = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
            final_text = format_profile_result(user_name, analysis_result_json, ai_comment)
        else:
            ai_comment = await gpt_analyzer.get_stats_professional_commentary(user_name, analysis_result_json)
            final_text = format_player_stats_result(user_name, analysis_result_json, ai_comment)

    if analysis_type == "player_stats":
        win_rate = analysis_result_json.get("main_indicators", {}).get("win_rate")
        if win_rate and float(win_rate) > 60:
            final_text = COMMENT_TEMPLATES["high_win_rate"].format(user=user_name) + "\n\n" + final_text

    await bot.edit_message_caption(chat_id=callback_query.message.chat.id, 
                                   message_id=callback_query.message.message_id, 
                                   caption=final_text, 
                                   parse_mode=ParseMode.HTML)
    await state.clear()

def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func) -> None:
    """Реєстрація обробників команд і колбеків."""
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    dp.message.register(cmd_analyze_player_stats, Command("analyzestats"))
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    dp.callback_query.register(trigger_vision_analysis_callback, F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)

# Примітка: Додайте обробники для "quick_overview" та "delete_bot_message", якщо потрібно.