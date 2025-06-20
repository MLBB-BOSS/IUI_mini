"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Розширено для підтримки повного життєвого циклу управління паті.
"""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Створює клавіатуру для підтвердження наміру користувача створити паті."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, допоможи", callback_data="party_start_creation")
    builder.button(text="❌ Ні, я сам", callback_data="party_cancel_creation")
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str], callback_prefix: str) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі.
    Стала більш гнучкою за рахунок кастомного префіксу для callback.

    Args:
        available_roles: Список доступних ролей для вибору.
        callback_prefix: Префікс для callback_data (напр. 'party_role_select' або 'party_join_role_select').
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {
        "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
        "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
    }
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"{callback_prefix}:{role}")
    builder.adjust(1)
    return builder.as_markup()

def create_dynamic_lobby_keyboard(lobby_id: str) -> InlineKeyboardMarkup:
    """
    Створює універсальну клавіатуру для активного лобі.
    Кнопки тепер не залежать від користувача, що є більш правильною архітектурою.
    Перевірка прав доступу відбувається в обробниках.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Приєднатися", callback_data=f"party_join:{lobby_id}")
    builder.button(text="❌ Вийти з паті", callback_data=f"party_leave:{lobby_id}")
    builder.button(text="🚫 Скасувати лобі", callback_data=f"party_cancel_lobby:{lobby_id}")
    builder.adjust(2, 1) # Розміщуємо кнопки в два стовпці, а останню - в один
    return builder.as_markup()
