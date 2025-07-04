"""
Визначення станів FSM для процесу реєстрації та оновлення профілю.
"""
from aiogram.fsm.state import State, StatesGroup

class ProfileRegistration(StatesGroup):
    """
    Машина станів для реєстрації та керування профілем користувача.
    """
    # Первинна реєстрація
    waiting_for_initial_photo = State()

    # Стани для оновлення конкретних даних
    waiting_for_basic_photo_update = State()
    waiting_for_stats_photo_update = State()
    waiting_for_heroes_photo_update = State()

    # Стан для підтвердження видалення профілю
    confirming_deletion = State()
