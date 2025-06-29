"""
Визначення станів FSM для процесів, пов'язаних з користувачем.
"""
from aiogram.fsm.state import StatesGroup, State

class RegistrationFSM(StatesGroup):
    """
    Стани для покрокового процесу реєстрації користувача.
    """
    waiting_for_photo = State()        # Очікування на скріншот профілю
    waiting_for_confirmation = State() # Очікування на підтвердження даних
