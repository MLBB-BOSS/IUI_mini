"""
Двигун Контексту для збору та аналізу даних перед генерацією промпту.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal

from config import logger
from utils.cache_manager import load_user_cache

# 💎 ОНОВЛЕНО: Додаємо новий стан до типу Intent
Intent = Literal[
    "technical_help", "emotional_support", "celebration", 
    "casual_chat", "ambiguous_request", "neutral"
]
TimeOfDay = Literal["morning", "afternoon", "evening", "night"]

@dataclass
class ContextVector:
    """
    Структура для зберігання повної контекстної інформації про запит.
    """
    user_id: int
    user_profile: Dict[str, Any] | None = None
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    last_message_intent: Intent = "neutral"
    time_of_day: TimeOfDay = "afternoon"

def _analyze_user_intent(message_text: str) -> Intent:
    """
    Визначає намір користувача для адаптації стилю відповіді.
    💎 ОНОВЛЕНО: Розширено словники патернів та оптимізовано порядок перевірок.
    """
    text_lower = message_text.lower()

    # --- 1. Пріоритетна перевірка на неоднозначність ---
    AMBIGUOUS_PATTERNS = [
        r'\b(вибісив|бісить|дратує|задовбало|це жах|я в шоці)\b',
        r'\b(таке собі|не дуже|погано все)\b'
    ]
    GAME_CONTEXT_KEYWORDS = [
        r'\b(гра|грі|катка|катку|матч|тімейт|ранг|мід|бот|топ|герой|персонаж|мвп|savage)\b'
    ]
    is_ambiguous = any(re.search(p, text_lower) for p in AMBIGUOUS_PATTERNS)
    has_game_context = any(re.search(kw, text_lower) for kw in GAME_CONTEXT_KEYWORDS)

    if is_ambiguous and not has_game_context:
        logger.info("Виявлено неоднозначний запит без ігрового контексту.")
        return "ambiguous_request"

    # --- 2. Перевірка на сильні емоційні сигнали (негативні) ---
    EMOTIONAL_PATTERNS = [
        # Поразка / Фрустрація
        r'\b(злив|програв|тілт|дно|раки|фідоня|фідити|ненавиджу)\b',
        # Роздратування
        r'\b(капець|бездарі|втомився|задовбали)\b',
        # Загальні емоційні маркери
        r'(!{2,}|\.{3,})', 
        r'\b(😭|😡|🤬|😤|😩|💀)\b'
    ]
    if any(re.search(p, text_lower) for p in EMOTIONAL_PATTERNS):
        return "emotional_support"

    # --- 3. Перевірка на сильні емоційні сигнали (позитивні) ---
    CELEBRATION_PATTERNS = [
        # Перемога / Похвала
        r'\b(gg|ez|ізі|виграв|переміг|апнув|тащу|затащив|красава|топ|імба)\b',
        # Ігрові досягнення
        r'\b(mvp|мвп|savage|саваж|маньяк)\b',
        # Позитивні емодзі
        r'\b(🤣|😂|😎|🏆|🔥|💪|🥳)\b'
    ]
    if any(re.search(p, text_lower) for p in CELEBRATION_PATTERNS):
        return "celebration"
    
    # --- 4. Перевірка на технічні запити / прохання про допомогу ---
    HELP_PATTERNS = [
        # Прямі запитання
        r'\b(допоможи|як|що робити|порадь|підкажи|навчи|поясни|розкажи)\b',
        # Запити про предмети / героїв
        r'\b(який|яка|яке|які|кого)\s+(білд|предмет|емблема|збірку|героя|пікнути)',
        r'\b(що|шо)\s+(збирати|качати|купити)',
        # Прямий знак питання в кінці
        r'\?$',
    ]
    if any(re.search(p, text_lower) for p in HELP_PATTERNS):
        return "technical_help"

    # --- 5. Перевірка на невимушену розмову (після всіх специфічних) ---
    CASUAL_PATTERNS = [
        # Привітання / Загальні фрази
        r'\b(привіт|йоу|хай|рофл|лол|кек|чіл|брате|здоров|ку)\b',
        # Короткі відповіді
        r'^(ага|ок|норм|да|ні|неа|зрозумів|дякую)',
        # Нейтральні/позитивні емодзі
        r'\b(😅|🤡|👍|✊|😉)\b'
    ]
    if any(re.search(p, text_lower) for p in CASUAL_PATTERNS):
        return "casual_chat"

    # --- 6. Якщо нічого не підійшло, повертаємо нейтральний намір ---
    return "neutral"

def _get_time_of_day() -> TimeOfDay:
    """
    Визначає поточний час доби за Київським часом.
    """
    kyiv_tz = timezone(timedelta(hours=3))
    current_hour = datetime.now(kyiv_tz).hour

    if 5 <= current_hour < 12:
        return "morning"
    if 12 <= current_hour < 17:
        return "afternoon"
    if 17 <= current_hour < 22:
        return "evening"
    return "night"

async def gather_context(user_id: int, chat_history: List[Dict[str, str]]) -> ContextVector:
    """
    Збирає повний контекст для користувача та діалогу для MVP.

    Args:
        user_id: ID користувача Telegram.
        chat_history: Історія поточного діалогу.

    Returns:
        Заповнений об'єкт ContextVector.
    """
    logger.info(f"ContextEngine: Збір контексту для користувача {user_id}...")

    # 1. Завантажуємо профіль користувача
    user_profile = await load_user_cache(user_id)
    if not user_profile:
        logger.debug(f"ContextEngine: Профіль для {user_id} не знайдено, користувач не зареєстрований.")

    # 2. Аналізуємо намір останнього повідомлення
    last_message = ""
    if chat_history and chat_history[-1].get("role") == "user":
        last_message = str(chat_history[-1].get("content", ""))
    
    intent = _analyze_user_intent(last_message)
    logger.debug(f"ContextEngine: Визначено намір для {user_id} - '{intent}'.")

    # 3. Визначаємо час доби
    time_of_day = _get_time_of_day()
    logger.debug(f"ContextEngine: Визначено час доби - '{time_of_day}'.")

    # 4. Створюємо та повертаємо вектор контексту
    context_vector = ContextVector(
        user_id=user_id,
        user_profile=user_profile if user_profile else None,
        chat_history=chat_history,
        last_message_intent=intent,
        time_of_day=time_of_day
    )
    
    logger.info(f"ContextEngine: Контекст для {user_id} успішно зібрано.")
    return context_vector
