"""
Клавіатури для меню профілю.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Повертає інлайн-клавіатуру для головного меню профілю.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Оновити базові дані", callback_data="profile_update_basic")
    )
    builder.row(
        InlineKeyboardButton(text="📈 Додати загальну статистику", callback_data="profile_add_stats")
    )
    builder.row(
        InlineKeyboardButton(text="🦸 Додати статистику героїв", callback_data="profile_add_heroes")
    )
    builder.row(
        InlineKeyboardButton(text="🗑️ Видалити профіль", callback_data="profile_delete")
    )
    return builder.as_markup()

def get_confirm_delete_keyboard() -> InlineKeyboardMarkup:
    """
    Повертає інлайн-клавіатуру для підтвердження видалення профілю.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Так, видалити", callback_data="confirm_delete_yes"),
        InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="confirm_delete_no")
    )
    return builder.as_markup()
