"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Розширено для підтримки покрокового створення паті (FSM) та реєстрації.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

# --- КЛАВІАТУРИ ДЛЯ FSM СТВОРЕННЯ ПАТІ ---

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для підтвердження наміру користувача створити паті.
    Крок 1 нашого діалогу.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, допоможи", callback_data="party_start_creation")
    builder.button(text="❌ Ні, я сам", callback_data="party_cancel_creation")
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str]) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі ініціатором паті.
    Крок 2 нашого діалогу.

    Args:
        available_roles: Список доступних ролей для вибору.
    """
    builder = InlineKeyboardBuilder()
    # Карта емодзі для візуального покращення та кращого UX
    role_emoji_map = {
        "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
        "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
    }
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"party_role_select:{role}")
    builder.adjust(1)  # По одній кнопці в ряд для максимальної зручності на мобільних
    return builder.as_markup()

# --- ОНОВЛЕНА КЛАВІАТУРА ЛОБІ ---

def create_dynamic_lobby_keyboard(lobby_id: str, user_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для активного лобі.
    Кнопки змінюються залежно від ролі користувача (лідер, учасник, спостерігач).
    """
    builder = InlineKeyboardBuilder()
    players = lobby_data.get("players", {})
    leader_id = lobby_data.get("leader_id")

    # Кнопка "Приєднатися" видима для всіх, хто ще не в паті
    if user_id not in players:
        builder.button(text="➕ Приєднатися", callback_data=f"party_join:{lobby_id}")

    # Кнопка "Вийти" видима для всіх учасників, крім лідера
    if user_id in players and user_id != leader_id:
        builder.button(text="❌ Вийти з паті", callback_data=f"party_leave:{lobby_id}")

    # Кнопка "Скасувати" видима тільки для лідера паті
    if user_id == leader_id:
        builder.button(text="🚫 Скасувати лобі", callback_data=f"party_cancel_lobby:{lobby_id}")

    return builder.as_markup()

# === КЛАВІАТУРИ ДЛЯ РЕЄСТРАЦІЇ ТА ПРОФІЛЮ ===

def create_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Створює початкову, компактну клавіатуру для меню профілю.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚙️ Налаштувати", callback_data="profile_menu_expand"),
        InlineKeyboardButton(text="🏃 Вийти", callback_data="profile_menu_close")
    )
    return builder.as_markup()

def create_expanded_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Створює розширену клавіатуру для меню профілю з короткими написами.
    """
    builder = InlineKeyboardBuilder()
    # Використовуємо короткі та зрозумілі назви
    builder.button(text="🔄 Профіль", callback_data="profile_update_basic")
    builder.button(text="📈 Статистика", callback_data="profile_add_stats")
    builder.button(text="🦸 Герої", callback_data="profile_add_heroes")
    builder.button(text="🗑️ Видалити", callback_data="profile_delete")
    builder.button(text="◀️ Назад", callback_data="profile_menu_collapse")
    # Розташовуємо кнопки 2x2, а кнопку "Назад" окремим рядком
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def create_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура для підтвердження видалення профілю.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так", callback_data="delete_confirm_yes"),
            InlineKeyboardButton(text="❌ Ні", callback_data="delete_confirm_no")
        ]
    ])
