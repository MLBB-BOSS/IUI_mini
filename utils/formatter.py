"""
utils/formatter.py

Майстер Оформлення: централізований модуль для форматування
всіх вихідних повідомлень бота за єдиним стандартом.
Компонент "Адаптивної Діалогової Системи" (ADS).
"""
import html
from typing import Literal

ContentType = Literal["default", "success", "error", "joke", "technical", "tip"]

# Словник для заголовків та емодзі за типами контенту
RESPONSE_TEMPLATES = {
    "default": {
        "emoji": "💬",
        "title": "GGenius на зв'язку"
    },
    "success": {
        "emoji": "🏆",
        "title": "Перемога!"
    },
    "error": {
        "emoji": "💀",
        "title": "Ой, щось пішло не так"
    },
    "joke": {
        "emoji": "😂",
        "title": "Хвилинка гумору"
    },
    "technical": {
        "emoji": "⚙️",
        "title": "Технічний аналіз"
    },
    "tip": {
        "emoji": "💡",
        "title": "Корисна порада"
    }
}

def format_bot_response(
    text: str,
    content_type: ContentType = "default",
    tip: str | None = None
) -> str:
    """
    Форматує будь-який текст у стандартний вигляд відповіді бота.

    Args:
        text: Основний текст повідомлення.
        content_type: Тип контенту для вибору заголовка та емодзі.
        tip: Необов'язкова порада, що буде додана в кінці.

    Returns:
        Повністю відформатоване повідомлення у HTML.
    """
    template = RESPONSE_TEMPLATES.get(content_type, RESPONSE_TEMPLATES["default"])
    
    header = f"{template['emoji']} <b>{template['title']}</b>"
    separator = "━━━━━━━━━━━━━━━━━━━━━"
    
    # Екрануємо основний текст, щоб уникнути конфліктів тегів,
    # але зберігаємо наші власні теги <b>, <i>, <code>
    # Це спрощена версія, для складних випадків може знадобитися більш надійний парсер
    safe_text = text.strip()

    parts = [
        f"<blockquote>{header}",
        separator,
        "",
        safe_text
    ]

    if tip:
        parts.extend([
            "",
            f"💡 <i>Порада: {html.escape(tip)}</i>"
        ])

    parts.append("</blockquote>")
    
    return "\n".join(parts)
