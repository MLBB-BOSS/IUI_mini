"""
utils/formatter.py

Майстер Оформлення: централізований модуль для форматування
всіх вихідних повідомлень бота за єдиним стандартом.
Компонент "Адаптивної Діалогової Системи" (ADS).
"""
import html
import re
from typing import Literal

# Перейменовано для кращої семантики
ResponseType = Literal["default", "success", "error", "joke", "technical", "tip"]

# Словник для заголовків та емодзі за типами контенту
RESPONSE_TEMPLATES = {
    "default": {"emoji": "💬", "title": "GGenius на зв'язку"},
    "success": {"emoji": "🏆", "title": "Перемога!"},
    "error": {"emoji": "💀", "title": "Ой, щось пішло не так"},
    "joke": {"emoji": "😂", "title": "Хвилинка гумору"},
    "technical": {"emoji": "⚙️", "title": "Технічний аналіз"},
    "tip": {"emoji": "💡", "title": "Корисна порада"}
}

def _sanitize_html(text: str) -> str:
    """
    Очищає текст від непідтримуваних Telegram HTML-тегів.
    Замінює <br> на новий рядок.
    """
    # Заміна <br> та <br/> на символ нового рядка
    sanitized_text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    return sanitized_text.strip()

def format_bot_response(
    text: str,
    response_type: ResponseType = "default",
    tip: str | None = None
) -> str:
    """
    Форматує будь-який текст у стандартний вигляд відповіді бота.
    Для типів 'default', 'joke', 'success' повертає "сирий" текст для природного спілкування.

    Args:
        text: Основний текст повідомлення.
        response_type: Тип контенту для вибору стилю відповіді.
        tip: Необов'язкова порада, що буде додана в кінці.

    Returns:
        Повністю відформатоване повідомлення у HTML або простому тексті.
    """
    # ШВИДКЕ РІШЕННЯ: Для звичайних розмовних відповідей повертаємо текст без обгортки
    if response_type in ["default", "joke", "success"]:
        return _sanitize_html(text)

    # Для інших типів (error, technical, tip) залишаємо структурований вигляд
    template = RESPONSE_TEMPLATES.get(response_type, RESPONSE_TEMPLATES["default"])
    
    header = f"{template['emoji']} <b>{template['title']}</b>"
    safe_text = _sanitize_html(text)

    parts = [header, "", safe_text]

    if tip:
        parts.extend(["", f"💡 <i>Порада: {html.escape(tip)}</i>"])
    
    return "\n".join(parts)
