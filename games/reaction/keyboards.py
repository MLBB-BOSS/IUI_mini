"""
Модуль для створення інлайн-клавіатур для гри на реакцію.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def create_reaction_game_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру з однією кнопкою для гри на реакцію.

    Returns:
        Інлайн-клавіатура з кнопкою "НАТИСКАЙ!".
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔴 НАТИСКАЙ! 🔴",
        callback_data="reaction_game:stop"
    )
    return builder.as_markup()
