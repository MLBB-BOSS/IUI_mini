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

def create_role_selection_keyboard(available_roles: List[str], lobby_id: str) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі при приєднанні до паті.
    Крок 2 діалогу приєднання.

    Args:
        available_roles: Список доступних ролей для вибору.
        lobby_id: ID лобі, до якого приєднується гравець.
    """
    builder = InlineKeyboardBuilder()
    # Карта емодзі для візуального покращення та кращого UX
    role_emoji_map = {
        "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
        "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
    }
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        # Тепер callback_data включає ID лобі для правильної обробки
        builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
    builder.adjust(1)  # По одній кнопці в ряд для максимальної зручності на мобільних
    # Додаємо кнопку скасування, якщо користувач передумав обирати роль
    builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data=f"party_cancel_join:{lobby_id}"))
    return builder.as_markup()

# --- ОНОВЛЕНА УНІВЕРСАЛЬНА КЛАВІАТУРА ЛОБІ ---

def create_lobby_keyboard(lobby_id: str, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює універсальну клавіатуру для активного лобі.
    Кнопки "Покинути" та "Скасувати" видимі завжди, але логіка їх роботи
    перевіряється на бекенді. Кнопка "Приєднатися" зникає, коли лобі заповнене.
    """
    builder = InlineKeyboardBuilder()
    players = lobby_data.get("players", {})

    # Кнопка "Приєднатися" зникає, якщо в паті 5 гравців
    if len(players) < 5:
        builder.button(text="➕ Приєднатися", callback_data=f"party_join:{lobby_id}")

    # Ці кнопки видимі завжди, логіка їх роботи перевіряється на бекенді
    builder.button(text="❌ Покинути паті", callback_data=f"party_leave:{lobby_id}")
    builder.button(text="🚫 Скасувати лобі", callback_data=f"party_cancel_lobby:{lobby_id}")

    builder.adjust(1)
    return builder.as_markup()

# === КЛАВІАТУРИ ДЛЯ РЕЄСТРАЦІЇ ТА ПРОФІЛЮ ===

def create_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Створює початкову, компактну клавіатуру для меню профілю.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚙️ Налаштувати", callback_data="profile_menu_expand"),
        InlineKeyboardButton(text="🚪 Вийти", callback_data="profile_menu_close")
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
