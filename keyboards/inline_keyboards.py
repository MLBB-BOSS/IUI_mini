from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

# ... (код create_party_confirmation_keyboard та create_role_selection_keyboard без змін)
def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, створити", callback_data="party_create_yes")
    builder.button(text="❌ Ні, дякую", callback_data="party_create_no")
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for role in available_roles:
        builder.button(text=role, callback_data=f"party_role_select_{role}")
    builder.adjust(1)
    return builder.as_markup()


# --- НОВІ КЛАВІАТУРИ ---
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

def create_dynamic_lobby_keyboard(user_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для лобі, враховуючи роль користувача.
    """
    builder = InlineKeyboardBuilder()
    players = lobby_data.get("players", {})
    leader_id = lobby_data.get("leader_id")

    # Кнопка "Приєднатися" видима для всіх, хто ще не в паті
    if str(user_id) not in players:
        builder.button(text="➕ Приєднатися", callback_data="party_join")

    # Кнопка "Вийти" видима для всіх, хто вже в паті (крім лідера)
    if str(user_id) in players and user_id != leader_id:
        builder.button(text="❌ Вийти з паті", callback_data="party_leave")

    # Кнопка "Скасувати" видима тільки для лідера паті
    if user_id == leader_id:
        builder.button(text="🚫 Скасувати лобі", callback_data="party_cancel")

    return builder.as_markup()
