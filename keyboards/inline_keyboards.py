"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Повністю асинхронний та оптимізований для aiogram 3.x.
"""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для підтвердження наміру користувача створити паті.
    Використовується на першому кроці FSM.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, допомогти", callback_data="party_create_confirm")
    builder.button(text="❌ Ні, я сам", callback_data="party_create_cancel")
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str]) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі ініціатором паті.

    Args:
        available_roles: Список доступних ролей для вибору.
    """
    builder = InlineKeyboardBuilder()
    # Карта емодзі для візуального покращення
    role_emoji_map = {
        "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
        "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
    }
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"party_role_select_{role}")
    builder.adjust(1)  # По одній кнопці в ряд для максимальної зручності на мобільних
    return builder.as_markup()


def create_dynamic_lobby_keyboard(lobby_id: str, user_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для активного лобі.
    Кнопки змінюються залежно від того, чи є користувач лідером, учасником,
    чи стороннім спостерігачем.

    Args:
        lobby_id: Унікальний ідентифікатор лобі.
        user_id: ID користувача, для якого генерується клавіатура.
        lobby_data: Словник з даними про лобі.
    """
    builder = InlineKeyboardBuilder()
    players = lobby_data.get("players", {})
    leader_id = lobby_data.get("leader_id")

    # Кнопка "Приєднатися" видима для всіх, хто ще не в паті
    if user_id not in players:
        builder.button(text="➕ Приєднатися", callback_data=f"party_join:{lobby_id}")

    # Кнопка "Вийти" видима для всіх, хто вже в паті (крім лідера)
    if user_id in players and user_id != leader_id:
        builder.button(text="❌ Вийти з паті", callback_data=f"party_leave:{lobby_id}")

    # Кнопка "Скасувати" видима тільки для лідера паті
    if user_id == leader_id:
        builder.button(text="🚫 Скасувати лобі", callback_data=f"party_cancel_lobby:{lobby_id}")

    return builder.as_markup()

# --- Існуючі клавіатури ---
def create_party_size_keyboard() -> InlineKeyboardMarkup:
    """Створює клавіатуру для вибору формату паті."""
    builder = InlineKeyboardBuilder()
    sizes = {"Фулл (5)": 5, "Квадро (4)": 4, "Тріо (3)": 3, "Дуо (2)": 2}
    for text, size in sizes.items():
        builder.button(text=text, callback_data=f"party_size_{size}")
    builder.adjust(2)
    return builder.as_markup()

def create_lobby_lifetime_keyboard() -> InlineKeyboardMarkup:
    """Створює клавіатуру для вибору часу життя лобі."""
    builder = InlineKeyboardBuilder()
    lifetimes = {
        "30 хвилин": 1800, "1 година": 3600, "3 години": 10800,
        "6 годин": 21600, "12 годин": 43200
    }
    for text, seconds in lifetimes.items():
        builder.button(text=text, callback_data=f"party_lifetime_{seconds}")
    builder.adjust(2)
    return builder.as_markup()
