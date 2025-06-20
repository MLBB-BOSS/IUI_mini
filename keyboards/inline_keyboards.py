from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

# --- НОВА КЛАВІАТУРА ПІДТВЕРДЖЕННЯ ---
def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Створює клавіатуру для підтвердження дії створення паті."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, допомогти", callback_data="party_create_confirm")
    builder.button(text="❌ Ні, я сам", callback_data="party_create_cancel")
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str]) -> InlineKeyboardMarkup:
    """Створює клавіатуру для вибору ролі."""
    builder = InlineKeyboardBuilder()
    for role in available_roles:
        # Додамо емодзі для краси
        role_emoji_map = {
            "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
            "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
        }
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"party_role_select_{role}")
    builder.adjust(1) # По одній кнопці в ряд для кращої читабельності
    return builder.as_markup()

# --- Клавіатура лобі (без змін, але буде використовуватись по-новому) ---
def create_dynamic_lobby_keyboard(lobby_id: str, user_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для лобі, враховуючи роль користувача.
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
        builder.button(text="🚫 Скасувати лобі", callback_data=f"party_cancel:{lobby_id}")

    return builder.as_markup()

# ... решта клавіатур без змін ...
