"""
Модуль для створення інлайн-клавіатур для гри на реакцію.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def create_reaction_lobby_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для ігрового лобі "Reaction Time".
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Розпочати гру", callback_data="reaction_game:start")
    builder.button(text="🏆 Таблиця лідерів", callback_data="reaction_game:show_leaderboard")
    builder.button(text="◀️ Вийти", callback_data="reaction_game:exit")
    builder.adjust(1)
    return builder.as_markup()


def create_leaderboard_view_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для перегляду таблиці лідерів з кнопкою "Назад".
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад до меню", callback_data="reaction_game:show_lobby")
    return builder.as_markup()


def create_reaction_game_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру з однією кнопкою для активної фази гри.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 НАТИСКАЙ! 🔴", callback_data="reaction_game:stop")
    return builder.as_markup()
