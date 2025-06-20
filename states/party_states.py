"""
Модуль для визначення станів (FSM), пов'язаних зі створенням та управлінням паті.
"""
from aiogram.fsm.state import StatesGroup, State


class PartyCreation(StatesGroup):
    """
    Стани для покрокового процесу створення нового лобі для пошуку команди.
    """
    confirm_creation = State()  # Очікування підтвердження (Так/Ні)
    select_role = State()       # Очікування вибору ролі ініціатором
