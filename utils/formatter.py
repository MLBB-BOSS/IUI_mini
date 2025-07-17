"""
utils/formatter.py

Майстер Оформлення: централізований модуль для форматування
всіх вихідних повідомлень бота за єдиним стандартом.
Компонент "Адаптивної Діалогової Системи" (ADS).
"""
import html
import re
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

def _sanitize_html(text: str) -> str:
    """
    Очищає текст від непідтримуваних Telegram HTML-тегів.
    Замінює <br> на новий рядок та видаляє інші невалідні теги.
    """
    # Заміна тегів для перенесення рядка
    sanitized_text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    
    # Видалення непідтримуваних тегів, що можуть використовуватися для структурування (ul, li, p, div)
    # Замінюємо закриваючі теги на новий рядок для кращої читабельності
    sanitized_text = re.sub(r'</(li|p|div|ul|ol)>', '\n', sanitized_text, flags=re.IGNORECASE)
    # Видаляємо всі інші форми цих тегів
    sanitized_text = re.sub(r'<(/?)(ul|ol|li|p|div|span)\b[^>]*>', '', sanitized_text, flags=re.IGNORECASE)

    # Балансування основних тегів (b, i, code), якщо вони не закриті
    tags_to_balance = ["b", "i", "code"]
    for tag in tags_to_balance:
        open_tags = len(re.findall(f'<{tag}>', sanitized_text, re.IGNORECASE))
        close_tags = len(re.findall(f'</{tag}>', sanitized_text, re.IGNORECASE))
        if open_tags > close_tags:
            sanitized_text += f'</{tag}>' * (open_tags - close_tags)
            
    return sanitized_text.strip()

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
    
    # Спочатку очищаємо HTML, потім форматуємо
    safe_text = _sanitize_html(text)

    parts = [
        header,
        "",
        safe_text
    ]

    if tip:
        parts.extend([
            "",
            f"💡 <i>Порада: {html.escape(tip)}</i>"
        ])
    
    return "\n".join(parts)
