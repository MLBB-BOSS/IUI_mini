"""
Клавіатури для міні-гри на перевірку реакції.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def create_reaction_game_keyboard(state: str, game_id: int) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для гри на реакцію.
    
    Args:
        state: Поточний стан гри ('initial', 'wait', 'ready', 'finished').
        game_id: ID гри (повідомлення).
        
    Returns:
        Клавіатура для відповідного стану гри.
    """
    builder = InlineKeyboardBuilder()
    
    if state == "initial":
        # Початковий екран
        builder.button(text="🚀 Почати гру", callback_data="reaction_game_start")
        builder.button(text="🏆 Таблиця лідерів", callback_data="reaction_game_leaderboard")
    elif state == "wait":
        # Очікування зеленого сигналу
        builder.button(text="🔴", callback_data=f"reaction_game_press:{game_id}")
    elif state == "ready":
        # Зелений сигнал, час тиснути
        builder.button(text="🟢 ТИСНИ!", callback_data=f"reaction_game_press:{game_id}")
    elif state == "finished":
        # Кінець гри
        builder.button(text="🔄 Грати ще", callback_data="reaction_game_start")
        builder.button(text="🏆 Таблиця лідерів", callback_data="reaction_game_leaderboard")
        
    builder.adjust(2)
    return builder.as_markup()


def create_leaderboard_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для екрана таблиці лідерів.
    
    Returns:
        Клавіатура з кнопкою "Назад".
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад до гри", callback_data="reaction_game_back_to_menu")
    return builder.as_markup()
