"""
Визначення станів FSM для гри на реакцію.
"""
from aiogram.fsm.state import StatesGroup, State


class ReactionGameState(StatesGroup):
    """
    Стани для ігрового циклу "Reaction Time".
    """
    # ❗️ НОВИЙ СТАН: Користувач знаходиться в ігровому меню (лобі)
    menu = State()
    
    # Стан, в якому гравець очікує на зелене світло,
    # щоб натиснути кнопку.
    in_progress = State()
