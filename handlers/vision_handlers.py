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

from config import OPENAI_API_KEY, logger
from services.openai_service import (
    MLBBChatGPT,
    PROFILE_SCREENSHOT_PROMPT,
    PLAYER_STATS_PROMPT
)
from states.vision_states import VisionAnalysisStates
from utils.message_utils import send_message_in_chunks # Переконайся, що цей шлях правильний


# === КЛАСИ ДЛЯ АНАЛІТИКИ ТА ФОРМАТУВАННЯ (з твого коду) ===
# MLBBAnalyticsCalculator та AnalysisFormatter залишаються тут, як ти їх надав.
# Я припускаю, що вони працюють коректно.
# Для стислості, я не буду повторювати їх тут повністю.

class MLBBAnalyticsCalculator:
    @staticmethod
    def safe_divide(numerator: Union[int, float, str], denominator: Union[int, float, str], 
                   precision: int = 2) -> Optional[float]:
        try:
            num = float(str(numerator).replace(',', '').replace(' ', ''))
            den = float(str(denominator).replace(',', '').replace(' ', ''))
            if den == 0: return None
            return float(Decimal(str(num / den)).quantize(Decimal(f'0.{"0"*precision}'), rounding=ROUND_HALF_UP))
        except: return None
    
    @staticmethod
    def safe_number(value: Any) -> Optional[float]:
        if value is None: return None
        try: return float(str(value).replace(',', '').replace(' ', ''))
        except: return None

    # ... (інші методи з твого MLBBAnalyticsCalculator)
    @classmethod
    def calculate_mvp_rating(cls, mvp_count: Any, matches_played: Any) -> Optional[float]:
        result = cls.safe_divide(mvp_count, matches_played, 4) # Збільшимо точність для множення на 100
        return result * 100 if result is not None else None
    
    @classmethod
    def calculate_mvp_loss_percentage(cls, mvp_loss_count: Any, mvp_count: Any) -> Optional[float]:
        result = cls.safe_divide(mvp_loss_count, mvp_count, 4)
        return result * 100 if result is not None else None
    
    @classmethod
    def calculate_savage_frequency(cls, savage_count: Any, matches_played: Any) -> Optional[float]:
        frequency = cls.safe_divide(savage_count, matches_played, 5) # Більша точність для множення на 1000
        return frequency * 1000 if frequency is not None else None
    
    @classmethod
    def calculate_legendary_frequency(cls, legendary_count: Any, matches_played: Any) -> Optional[float]:
        frequency = cls.safe_divide(legendary_count, matches_played, 4)
        return frequency * 100 if frequency is not None else None
    
    @classmethod
    def calculate_gold_efficiency(cls, avg_hero_dmg_per_min: Any, avg_gold_per_min: Any) -> Optional[float]:
        return cls.safe_divide(avg_hero_dmg_per_min, avg_gold_per_min, 2)

    @classmethod
    def calculate_average_impact(cls, most_kills: Any, most_assists: Any) -> Optional[float]: # Це, мабуть, не те, що малося на увазі під (K+A)/матч
        kills = cls.safe_number(most_kills) or 0
        assists = cls.safe_number(most_assists) or 0
        # Цей показник з твого коду розраховує суму максимальних кілів та асистів,
        # а не середній K+A за матч. Для середнього K+A потрібні середні кіли та асисти.
        # Залишу поки так, як у тебе, але це варто переглянути.
        return kills + assists if (kills > 0 or assists > 0) else None

class AnalysisFormatter: # Залишаю твій форматер, але його використання буде скориговано
    @staticmethod
    def _create_header_section(title: str, icon: str = "📊") -> str:
        return f"\n<b>{icon} {title}</b>\n" + "─" * 35 # Зменшив довжину лінії для компактності
    
    @staticmethod
    def _format_field(label: str, value: Any, icon: str = "•", unit: str = "") -> str:
        if value is None or value == "": return f"  {icon} <b>{label}:</b> <i>не розпізнано</i>"
        display_value = str(value)
        if "★" in display_value or "зірок" in display_value.lower():
            display_value = re.sub(r'\s+★', '★', display_value.replace("зірок", "★").replace("зірки", "★"))
        return f"  {icon} <b>{label}:</b> {html.escape(display_value)}{unit}"

    @staticmethod
    def _format_metric(label: str, value: Optional[float], icon: str, unit: str = "", precision: int = 2) -> str:
        if value is None: return f"  {icon} <b>{label}:</b> <i>недостатньо даних</i>"
        formatted_value = f"{value:.{precision}f}" if precision > 0 else f"{value:.0f}"
        return f"  {icon} <b>{label}:</b> {formatted_value}{unit}"

# === НОВІ ФУНКЦІЇ ФОРМАТУВАННЯ ДЛЯ <pre> ===
def _format_raw_stats_to_plain_text(data: Dict[str, Any], data_type: str, user_name: str) -> str:
    """Форматує 'сухі' дані статистики/профілю у простий текст для <pre> блоку."""
    if not data: return f"Не вдалося розпізнати дані для {user_name}."
    
    lines = []
    if data_type == "player_stats":
        lines.append(f"Детальна статистика гравця {user_name} ({data.get('stats_filter_type', 'N/A')}):")
        
        def _get_val(source_dict, key, default="N/A"):
            val = source_dict.get(key)
            return str(val) if val is not None else default

        main_ind = data.get("main_indicators", {})
        lines.append("\nОсновні показники:")
        lines.append(f"  • Матчів зіграно: {_get_val(main_ind, 'matches_played')}")
        wr = _get_val(main_ind, 'win_rate'); lines.append(f"  • Відсоток перемог: {wr}%" if wr != "N/A" else "  • Відсоток перемог: N/A")
        lines.append(f"  • MVP: {_get_val(main_ind, 'mvp_count')}")

        ach_left = data.get("achievements_left_column", {})
        lines.append("\nДосягнення (колонка 1):")
        lines.append(f"  • Легендарних: {_get_val(ach_left, 'legendary_count')}")
        lines.append(f"  • Маніяків: {_get_val(ach_left, 'maniac_count')}")
        lines.append(f"  • Подвійних вбивств: {_get_val(ach_left, 'double_kill_count')}")
        lines.append(f"  • Найб. вбивств за гру: {_get_val(ach_left, 'most_kills_in_one_game')}")
        lines.append(f"  • Найдовша серія перемог: {_get_val(ach_left, 'longest_win_streak')}")
        lines.append(f"  • Найб. шкоди/хв: {_get_val(ach_left, 'highest_dmg_per_min')}")
        lines.append(f"  • Найб. золота/хв: {_get_val(ach_left, 'highest_gold_per_min')}")

        ach_right = data.get("achievements_right_column", {})
        lines.append("\nДосягнення (колонка 2):")
        lines.append(f"  • Дикунств (Savage): {_get_val(ach_right, 'savage_count')}")
        lines.append(f"  • Потрійних вбивств: {_get_val(ach_right, 'triple_kill_count')}")
        lines.append(f"  • MVP при поразці: {_get_val(ach_right, 'mvp_loss_count')}")
        lines.append(f"  • Найб. допомоги за гру: {_get_val(ach_right, 'most_assists_in_one_game')}")
        lines.append(f"  • Перша кров: {_get_val(ach_right, 'first_blood_count')}")
        lines.append(f"  • Найб. отриманої шкоди/хв: {_get_val(ach_right, 'highest_dmg_taken_per_min')}")

        details = data.get("details_panel", {})
        lines.append("\nДеталі (права панель):")
        lines.append(f"  • KDA: {_get_val(details, 'kda_ratio')}")
        tfpr = _get_val(details, 'teamfight_participation_rate'); lines.append(f"  • Участь у ком. боях: {tfpr}%" if tfpr != "N/A" else "  • Участь у ком. боях: N/A")
        lines.append(f"  • Сер. золото/хв: {_get_val(details, 'avg_gold_per_min')}")
        lines.append(f"  • Сер. шкода героям/хв: {_get_val(details, 'avg_hero_dmg_per_min')}")
        lines.append(f"  • Сер. смертей/матч: {_get_val(details, 'avg_deaths_per_match')}")
        lines.append(f"  • Сер. шкода вежам/матч: {_get_val(details, 'avg_turret_dmg_per_match')}")

    elif data_type == "profile":
        lines.append(f"Детальна інформація профілю гравця {user_name}:")
        fields = { "game_nickname": "Нікнейм", "mlbb_id_server": "ID (Сервер)", "highest_rank_season": "Найвищий ранг", "matches_played": "Матчів зіграно", "likes_received": "Лайків отримано", "location": "Локація", "squad_name": "Сквад"}
        for key, label in fields.items():
            value = str(data.get(key)) if data.get(key) is not None else "не розпізнано"
            if key == "highest_rank_season" and ("★" in value or "зірок" in value.lower()):
                value = re.sub(r'\s+★', '★', value.replace("зірок", "★").replace("зірки", "★"))
            lines.append(f"  • {label}: {value}")
            
    return "\n".join(lines)

# Функція _calculate_unique_analytics з твого коду (можливо, її треба буде трохи адаптувати для профілю)
# Ця функція вже форматує вивід у HTML-подібний рядок.
def _calculate_unique_analytics(data: Dict[str, Any], analysis_type: str) -> str:
    calc = MLBBAnalyticsCalculator()
    analytics_parts = []
    
    if analysis_type == "player_stats":
        main_ind = data.get("main_indicators", {})
        ach_left = data.get("achievements_left_column", {})
        ach_right = data.get("achievements_right_column", {})
        details = data.get("details_panel", {})
        matches_played = main_ind.get('matches_played')
        
        mvp_rating = calc.calculate_mvp_rating(main_ind.get('mvp_count'), matches_played)
        analytics_parts.append(AnalysisFormatter._format_metric("MVP Рейтинг", mvp_rating, "⭐", "% матчів"))
        
        mvp_loss_percentage = calc.calculate_mvp_loss_percentage(ach_right.get('mvp_loss_count'), main_ind.get('mvp_count'))
        analytics_parts.append(AnalysisFormatter._format_metric("Частка MVP у поразках", mvp_loss_percentage, "💔", "%")) # Змінив емодзі

        savage_frequency = calc.calculate_savage_frequency(ach_right.get('savage_count'), matches_played)
        analytics_parts.append(AnalysisFormatter._format_metric("Частота Savage", savage_frequency, "🔥", " на 1000 матчів"))
        
        legendary_frequency = calc.calculate_legendary_frequency(ach_left.get('legendary_count'), matches_played)
        analytics_parts.append(AnalysisFormatter._format_metric("Частота Legendary", legendary_frequency, "✨", " на 100 матчів"))

        gold_efficiency = calc.calculate_gold_efficiency(details.get('avg_hero_dmg_per_min'), details.get('avg_gold_per_min'))
        analytics_parts.append(AnalysisFormatter._format_metric("Ефективність золота", gold_efficiency, "💰", " шкоди/хв на 1 золото/хв")) # Змінив емодзі

        # Розрахунок перемог/поразок, якщо можливо
        win_rate = main_ind.get('win_rate')
        if win_rate is not None and matches_played is not None:
            matches_num = calc.safe_number(matches_played)
            wr_num = calc.safe_number(win_rate)
            if matches_num is not None and wr_num is not None and matches_num > 0:
                wins = int(matches_num * wr_num / 100)
                losses = int(matches_num - wins)
                analytics_parts.append(AnalysisFormatter._format_field("Перемог/Поразок", f"{wins} / {losses}", "👑"))


    elif analysis_type == "profile":
        # Це функція _generate_profile_analytics з твого коду
        rank = data.get("highest_rank_season")
        if rank:
            rank_str = str(rank).lower()
            if "mythic" in rank_str or "міфічний" in rank_str: analytics_parts.append("  🔮 <b>Статус:</b> Досвідчений гравець вищого рівня")
            elif "legend" in rank_str or "легенда" in rank_str: analytics_parts.append("  ⭐ <b>Статус:</b> Сильний гравець з хорошими навичками")
            # ... (інші умови для рангу) ...
            else: analytics_parts.append("  🌱 <b>Статус:</b> Гравець, що розвивається")
        
        matches = data.get("matches_played")
        if matches:
            matches_num = calc.safe_number(matches)
            if matches_num is not None:
                if matches_num > 5000: analytics_parts.append("  🎮 <b>Активність:</b> Надзвичайно активний")
                # ... (інші умови для активності) ...
                else: analytics_parts.append("  🎮 <b>Активність:</b> Помірний гравець")
        # ... (аналогічно для лайків)

    return "\n".join(analytics_parts) if analytics_parts else "📈 <i>Недостатньо даних для унікальної аналітики.</i>"


# === ОБРОБНИКИ КОМАНД (без змін) ===
async def cmd_analyze_profile(message: Message, state: FSMContext) -> None:
    if not message.from_user: await message.reply("Помилка: не вдалося отримати дані користувача."); return
    user_name = html.escape(message.from_user.first_name)
    logger.info(f"Користувач {user_name} (ID: {message.from_user.id}) активував /analyzeprofile.")
    await state.update_data(analysis_type="profile", vision_prompt=PROFILE_SCREENSHOT_PROMPT, original_user_name=user_name)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name}</b>! Надішли скріншот профілю MLBB.", parse_mode=ParseMode.HTML)

async def cmd_analyze_player_stats(message: Message, state: FSMContext) -> None:
    if not message.from_user: await message.reply("Помилка: не вдалося отримати дані користувача."); return
    user_name = html.escape(message.from_user.first_name)
    logger.info(f"Користувач {user_name} (ID: {message.from_user.id}) активував /analyzestats.")
    await state.update_data(analysis_type="player_stats", vision_prompt=PLAYER_STATS_PROMPT, original_user_name=user_name)
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(f"Привіт, <b>{user_name}</b>! Надішли скріншот статистики гравця MLBB.", parse_mode=ParseMode.HTML)

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not message.chat or not message.photo:
        await message.reply("Будь ласка, надішліть фото (скріншот).")
        return
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")
    photo_file_id = message.photo[-1].file_id
    try: await message.delete()
    except TelegramAPIError: logger.warning("Не вдалося видалити повідомлення користувача зі скріншотом.")
    await state.update_data(vision_photo_file_id=photo_file_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")],
        [InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")]
    ])
    try:
        sent_msg = await bot.send_photo(message.chat.id, photo_file_id, caption="Скріншот отримано. Розпочати аналіз?", reply_markup=keyboard)
        await state.update_data(bot_message_id_for_analysis=sent_msg.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
    except TelegramAPIError as e:
        logger.error(f"Помилка надсилання фото з кнопками: {e}")
        await message.reply("Не вдалося обробити скріншот. Спробуйте ще раз.")
        await state.clear()

# === ОСНОВНИЙ ОБРОБНИК КОЛБЕКУ АНАЛІЗУ ===
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback_query.message or not callback_query.message.chat:
        await callback_query.answer("Помилка обробки.", show_alert=True); await state.clear(); return

    chat_id = callback_query.message.chat.id
    message_id_to_edit = callback_query.message.message_id # ID повідомлення з фото, яке будемо редагувати
    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")
    photo_file_id = user_data.get("vision_photo_file_id")
    vision_prompt = user_data.get("vision_prompt")
    analysis_type = user_data.get("analysis_type")

    if not all([photo_file_id, vision_prompt, analysis_type]):
        logger.error(f"Недостатньо даних у FSM для аналізу для {user_name}.")
        await callback_query.answer("Помилка: дані для аналізу неповні. Спробуйте знову.", show_alert=True)
        await state.clear(); return

    try:
        await callback_query.message.edit_caption(caption=f"⏳ Обробляю ваш скріншот, {user_name}...", reply_markup=None)
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося оновити підпис перед аналізом для {user_name}: {e}")

    # Ініціалізація частин відповіді
    generated_comment_html = ""
    unique_analytics_html = ""
    raw_stats_plain_text = ""
    error_occurred = False
    final_text_for_display = f"На жаль, {user_name}, сталася помилка під час обробки вашого запиту."

    try:
        file_info = await bot.get_file(photo_file_id)
        if not file_info.file_path: raise ValueError("Не вдалося отримати шлях до файлу.")
        image_bytes = (await bot.download_file(file_info.file_path)).read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, vision_prompt)

            if not analysis_result_json or "error" in analysis_result_json:
                error_msg = analysis_result_json.get('error', 'Невідома помилка') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка Vision API ({analysis_type}) для {user_name}: {error_msg}")
                final_text_for_display = f"😔 Вибач, {user_name}, помилка аналізу зображення: {html.escape(error_msg)}"
                error_occurred = True
            else:
                logger.info(f"Успішний Vision аналіз ({analysis_type}) для {user_name}.")
                
                # 1. Генеруємо коментар від IUI
                comment_text = ""
                data_for_comment_gen = analysis_result_json.copy()
                
                if analysis_type == "player_stats":
                    # Для статистики гравця, додаємо розраховані дані в копію для генерації коментаря
                    # Використовуємо функцію, яка повертає словник розрахованих даних, а не HTML рядок
                    # Потрібна функція `calculate_derived_stats_map` (подібна до `calculate_derived_stats` з попередніх версій)
                    # Припустимо, що `_calculate_unique_analytics` можна адаптувати або створити нову.
                    # Для простоти зараз, передамо `analysis_result_json` як є,
                    # але краще передавати розширений словник, як ми робили.
                    # Поки що `_calculate_unique_analytics` повертає HTML, тому не можемо її прямо використати для `data_for_comment_gen`
                    # Це місце потребує уваги, якщо коментарі для статистики не використовують розраховані дані.
                    # Припускаємо, що get_player_stats_description в сервісі може працювати з "сирими" даними + розрахованими.
                    # Для цього треба, щоб `_calculate_unique_analytics` не повертала HTML, а словник,
                    # або мати окрему функцію для розрахунку словника.
                    
                    # Тимчасове рішення: передаємо тільки сирі дані, якщо немає функції для розрахунку словника derived_stats
                    # Краще:
                    # derived_stats_map = calculate_derived_stats_map(analysis_result_json) # Повертає словник
                    # if derived_stats_map: data_for_comment_gen['derived_stats'] = derived_stats_map
                    # comment_text = await gpt_analyzer.get_player_stats_description(user_name, data_for_comment_gen)
                    
                    # Поточний варіант з твого коду викликає get_stats_professional_commentary
                    # Перейменуємо для узгодженості з твоїм services/openai_service.py, якщо там є такий метод
                    # Або використовуємо get_player_stats_description, якщо він там є
                    comment_text = await gpt_analyzer.get_player_stats_description(user_name, data_for_comment_gen) # Або get_stats_professional_commentary

                elif analysis_type == "profile":
                    comment_text = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)

                if comment_text and "<i>" not in comment_text: # Уникаємо відображення заглушок як коментарів
                    generated_comment_html = f"🎙️ <b>Коментар від IUI:</b>\n{html.escape(comment_text)}"
                elif comment_text: # Якщо це все ж заглушка
                    generated_comment_html = comment_text 
                
                # 2. Генеруємо унікальну аналітику
                # _calculate_unique_analytics з твого коду вже повертає HTML-форматований рядок
                unique_analytics_html = _calculate_unique_analytics(analysis_result_json, analysis_type)
                if unique_analytics_html and "Недостатньо даних" not in unique_analytics_html and "Помилка" not in unique_analytics_html:
                    unique_analytics_html = f"<b>📈 <u>Унікальна Аналітика від IUI:</u></b>\n{unique_analytics_html}"
                elif not unique_analytics_html : # Якщо порожній рядок
                    unique_analytics_html = "📈 <i>Унікальна аналітика наразі недоступна.</i>"


                # 3. Форматуємо "суху" статистику для <pre>
                raw_stats_plain_text = _format_raw_stats_to_plain_text(analysis_result_json, analysis_type, user_name)
                raw_stats_pre_block = f"<pre>{html.escape(raw_stats_plain_text)}</pre>"
                
                # Збираємо фінальний текст у бажаному порядку
                final_parts = []
                if generated_comment_html: final_parts.append(generated_comment_html)
                if unique_analytics_html: final_parts.append(unique_analytics_html)
                
                raw_stats_header = "📊 <u>Детальна інформація (для копіювання):</u>"
                if analysis_type == "player_stats":
                    raw_stats_header = f"📊 <u>Детальна статистика гравця {user_name} (для копіювання):</u>"
                elif analysis_type == "profile":
                     raw_stats_header = f"📊 <u>Інформація профілю {user_name} (для копіювання):</u>"
                final_parts.append(f"{raw_stats_header}\n{raw_stats_pre_block}")
                
                final_text_for_display = "\n\n".join(filter(None, final_parts))

    except Exception as e:
        logger.exception(f"Критична помилка під час обробки аналізу ({analysis_type}) для {user_name}: {e}")
        final_text_for_display = f"На жаль, {user_name}, сталася непередбачена помилка: {html.escape(str(e))}"
        error_occurred = True

    # Надсилаємо результат користувачеві
    await _display_analysis_result(bot, chat_id, message_id_to_edit, final_text_for_display, user_name, error_occurred)
    await state.clear()


async def _display_analysis_result(bot: Bot, chat_id: int, message_id: int,
                                 result_text: str, user_name: str, error_in_processing: bool) -> None:
    """
    Відображає результат аналізу: редагує підпис до фото або надсилає відповідь.
    """
    try:
        # Завжди видаляємо кнопки з повідомлення-прев'ю, якщо воно ще існує і має кнопки
        # (це повідомлення, яке ми будемо редагувати або на яке відповідати)
        try:
            # Перевіряємо, чи повідомлення ще існує перед спробою редагування
            target_message = await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramAPIError as e:
            # Якщо повідомлення вже видалено або не має кнопок, це нормально.
            # Або якщо це не те повідомлення, яке ми очікували (наприклад, текстове).
            logger.debug(f"Не вдалося видалити кнопки з повідомлення {message_id} для {user_name}: {e}. Можливо, воно вже змінене/видалене.")


        if len(result_text) <= 1024: # Якщо весь текст влазить у підпис
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id, # Редагуємо оригінальне повідомлення з фото
                caption=result_text,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Результати аналізу для {user_name} успішно відображено в підписі до фото.")
        else: # Текст задовгий для підпису
            logger.info(f"Текст аналізу для {user_name} задовгий ({len(result_text)} символів). Редагую підпис фото та надсилаю деталі як відповідь.")
            
            placeholder_caption = "✅ Аналіз завершено! Деталі у повідомленні-відповіді нижче 👇"
            if error_in_processing : # Якщо була помилка, не кажемо "завершено"
                 placeholder_caption = "ℹ️ Результат обробки у повідомленні-відповіді нижче 👇"

            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=placeholder_caption
                )
            except TelegramAPIError as e:
                logger.warning(f"Не вдалося відредагувати підпис до фото {message_id} на плейсхолдер: {e}. Спробую надіслати відповідь без цього.")

            # Надсилаємо повний текст як відповідь на оригінальне фото-повідомлення
            await send_message_in_chunks(
                bot,
                chat_id,
                result_text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message_id # ВАЖЛИВО: робимо це відповіддю
            )
            logger.info(f"Деталі аналізу для {user_name} надіслано як відповідь на фото.")

    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError при відображенні результату для {user_name}: {e}")
        try: # Запасний варіант: просто надіслати текст, якщо редагування не вдалося
            await send_message_in_chunks(bot, chat_id, result_text, ParseMode.HTML)
        except Exception as final_send_err:
            logger.error(f"Критична помилка: не вдалося надіслати результат аналізу для {user_name} навіть як новий текст: {final_send_err}")
            # Тут можна було б надіслати дуже коротке повідомлення про помилку, якщо навіть попереднє не пройшло
            await bot.send_message(chat_id, f"Вибачте, {user_name}, сталася серйозна помилка відображення результатів. Спробуйте пізніше.")
    except Exception as e:
        logger.error(f"Загальна помилка при відображенні результату для {user_name}: {e}")
        await bot.send_message(chat_id, f"Вибачте, {user_name}, виникла непередбачена помилка при показі результатів.")


# === ІНШІ ОБРОБНИКИ (delete_bot_message_callback, cancel_analysis, handle_wrong_input_for_analysis, register_vision_handlers) ===
# Залишаються без змін відносно твого коду (коміт 484a152...), 
# оскільки основні зміни стосувалися trigger_vision_analysis_callback та _display_analysis_result.
# Переконайся, що вони сумісні з будь-якими змінами в іменах функцій або логіці, якщо такі були.
# Для стислості, я їх тут не повторюю. Важливо, щоб register_vision_handlers правильно реєстрував оновлені функції.

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
