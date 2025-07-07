"""
Визначення станів FSM для процесів, пов'язаних з користувачем.
"""
from aiogram.fsm.state import StatesGroup, State

class RegistrationFSM(StatesGroup):
    """
    Стани для покрокового процесу реєстрації та оновлення профілю користувача.
    """
    # Початкова реєстрація
    waiting_for_photo = State()
    waiting_for_confirmation = State()
    
    # Оновлення даних
    waiting_for_basic_photo = State()      # Очікування скріншота з базовою інформацією
    waiting_for_stats_photo = State()      # Очікування скріншота зі загальною статистикою
    waiting_for_heroes_photo = State()     # Очікування скріншота зі статистикою героїв
    
    # Видалення
    confirming_deletion = State()