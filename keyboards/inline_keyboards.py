from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Створює клавіатуру з кнопками Так/Ні для пропозиції створення паті."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, створити", callback_data="party_create_yes")
    builder.button(text="❌ Ні, дякую", callback_data="party_create_no")
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str]) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі зі списку доступних.
    Кожна кнопка матиме унікальний callback_data з префіксом.
    """
    builder = InlineKeyboardBuilder()
    for role in available_roles:
        builder.button(text=role, callback_data=f"party_role_select_{role}")
    builder.adjust(1)  # Розміщуємо кожну кнопку на новому рядку для кращої читабельності
    return builder.as_markup()

def create_party_lobby_keyboard() -> InlineKeyboardMarkup:
    """Створює головну кнопку 'Приєднатися' для існуючого лобі."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Приєднатися", callback_data="join_party")
    return builder.as_markup()
