"""
Модуль Reply Keyboard для основної навігації бота.

Містить всі Reply клавіатури для спрощення взаємодії користувачів
з ботом через інтуїтивні кнопки замість текстових команд.
"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


# === КОНСТАНТИ КНОПОК ===
# Основні кнопки навігації
BTN_PROFILE = "🧑‍💼 Профіль"
BTN_STATISTICS = "📊 Статистика"  
BTN_GO = "🤖 GO"
BTN_PARTY = "🎮 Зібрати паті"

# Додаткові кнопки для різних сценаріїв
BTN_BACK = "◀️ Назад"
BTN_MAIN_MENU = "🏠 Головне меню"
BTN_HELP = "❓ Допомога"


def create_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Створює основну Reply клавіатуру з 4-ма головними кнопками.
    
    Макет:
    | 🧑‍💼 Профіль | 📊 Статистика |
    | 🤖 GO       | 🎮 Зібрати паті |
    
    Returns:
        ReplyKeyboardMarkup: Основна клавіатура навігації.
    """
    builder = ReplyKeyboardBuilder()
    
    # Перший ряд: Профіль та Статистика
    builder.add(
        KeyboardButton(text=BTN_PROFILE),
        KeyboardButton(text=BTN_STATISTICS)
    )
    
    # Другий ряд: GO та Зібрати паті
    builder.add(
        KeyboardButton(text=BTN_GO),
        KeyboardButton(text=BTN_PARTY)
    )
    
    # Налаштування макету: 2 кнопки в ряд
    builder.adjust(2, 2)
    
    return builder.as_markup(
        resize_keyboard=True,  # Адаптивний розмір
        persistent=True,       # Постійно видима
        one_time_keyboard=False  # Не зникає після натискання
    )


def create_go_keyboard() -> ReplyKeyboardMarkup:
    """
    Створює клавіатуру для режиму GO з можливістю повернення.
    
    Макет:
    | ❓ Допомога | 🏠 Головне меню |
    
    Returns:
        ReplyKeyboardMarkup: Клавіатура для GO режиму.
    """
    builder = ReplyKeyboardBuilder()
    
    builder.add(
        KeyboardButton(text=BTN_HELP),
        KeyboardButton(text=BTN_MAIN_MENU)
    )
    
    builder.adjust(2)
    
    return builder.as_markup(
        resize_keyboard=True,
        persistent=True,
        one_time_keyboard=False
    )


def create_analysis_keyboard() -> ReplyKeyboardMarkup:
    """
    Створює клавіатуру для режимів аналізу (профіль/статистика).
    
    Макет:
    | ◀️ Назад | 🏠 Головне меню |
    
    Returns:
        ReplyKeyboardMarkup: Клавіатура для режимів аналізу.
    """
    builder = ReplyKeyboardBuilder()
    
    builder.add(
        KeyboardButton(text=BTN_BACK),
        KeyboardButton(text=BTN_MAIN_MENU)
    )
    
    builder.adjust(2)
    
    return builder.as_markup(
        resize_keyboard=True,
        persistent=True,
        one_time_keyboard=False
    )


def get_keyboard_for_mode(mode: str) -> ReplyKeyboardMarkup:
    """
    Повертає відповідну клавіатуру для заданого режиму.
    
    Args:
        mode: Режим роботи ('main', 'go', 'analysis', 'party').
        
    Returns:
        ReplyKeyboardMarkup: Відповідна клавіатура.
    """
    keyboards = {
        "main": create_main_keyboard(),
        "go": create_go_keyboard(),
        "analysis": create_analysis_keyboard(),
        "party": create_main_keyboard()  # Для паті використовуємо основну
    }
    
    return keyboards.get(mode, create_main_keyboard())


# Експорт основних функцій та констант
__all__ = [
    "create_main_keyboard",
    "create_go_keyboard", 
    "create_analysis_keyboard",
    "get_keyboard_for_mode",
    "BTN_PROFILE",
    "BTN_STATISTICS",
    "BTN_GO", 
    "BTN_PARTY",
    "BTN_BACK",
    "BTN_MAIN_MENU",
    "BTN_HELP"
]
