"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Розширено для підтримки покрокового створення паті (FSM) та реєстрації.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

# Визначаємо константу ролей тут, щоб вона була доступна для всіх функцій
ALL_ROLES: List[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]

# --- 🔄 ОНОВЛЕНІ КЛАВІАТУРИ ДЛЯ FSM СТВОРЕННЯ ПАТІ ---

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для підтвердження наміру користувача створити паті.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так, допоможи", callback_data="party_start_creation")
    builder.button(text="❌ Ні, я сам", callback_data="party_cancel_creation")
    builder.adjust(2)
    return builder.as_markup()

def create_game_mode_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору режиму гри у два стовпчики.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Рейтинг", callback_data="party_set_mode:Ranked")
    builder.button(text="🎮 Класика", callback_data="party_set_mode:Classic")
    builder.button(text="⚔️ Режим бою", callback_data="party_set_mode:Brawl")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_confirmation")
    builder.adjust(2)
    return builder.as_markup()

def create_party_size_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору розміру паті у два стовпчики.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Дуо (2)", callback_data="party_set_size:2")
    builder.button(text="👥 Тріо (3)", callback_data="party_set_size:3")
    builder.button(text="👥 Фулл Паті (5)", callback_data="party_set_size:5")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_game_mode")
    builder.adjust(2)
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str], lobby_id: str) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі у два стовпчики.
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {
        "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
        "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
    }
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
    
    if lobby_id == "initial":
        builder.button(text="◀️ Назад", callback_data="party_step_back:to_party_size")
        builder.adjust(2) 
    else:
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="❌ Скасувати приєднання", callback_data=f"party_cancel_join:{lobby_id}"))
        
    return builder.as_markup()

def create_required_roles_keyboard(
    available_roles: List[str], 
    selected_roles: List[str], 
    num_to_select: int
) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору бажаних ролей з мультиселектом у два стовпчики.
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {"Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙", "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"}

    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        text = f"✅ {emoji} {role}" if role in selected_roles else f"{emoji} {role}"
        builder.button(text=text, callback_data=f"party_req_role:{role}")

    if len(selected_roles) == num_to_select:
        builder.button(text="👍 Підтвердити вибір", callback_data="party_confirm_roles")
    else:
        remaining = num_to_select - len(selected_roles)
        builder.button(text=f"⏳ Залишилось обрати: {remaining}", callback_data="party_dummy_button")

    builder.button(text="◀️ Назад", callback_data="party_step_back:to_leader_role")
    
    builder.adjust(2)
    return builder.as_markup()

def create_lobby_keyboard(lobby_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для активного лобі.
    """
    builder = InlineKeyboardBuilder()
    lobby_state = lobby_data.get("state", "open")
    
    if lobby_state == "joining":
        taken_roles = [p["role"] for p in lobby_data["players"].values()]
        required_roles = lobby_data.get('required_roles', [])
        if required_roles:
            available_roles = [r for r in required_roles if r not in taken_roles]
        else:
            available_roles = [r for r in ALL_ROLES if r not in taken_roles]
        
        role_emoji_map = {"Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙", "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"}
        for role in available_roles:
            emoji = role_emoji_map.get(role, "🔹")
            builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
        builder.adjust(2) 
        builder.row(InlineKeyboardButton(text="❌ Скасувати приєднання", callback_data=f"party_cancel_join:{lobby_id}"))

    else: # lobby_state == "open"
        players = lobby_data.get("players", {})
        party_size = lobby_data.get("party_size", 5)
        
        button_row = []
        if len(players) < party_size:
            button_row.append(InlineKeyboardButton(text="➕ Приєднатися", callback_data=f"party_join:{lobby_id}"))
        
        button_row.append(InlineKeyboardButton(text="❌ Покинути паті", callback_data=f"party_leave:{lobby_id}"))
        builder.row(*button_row)
        builder.row(InlineKeyboardButton(text="🚫 Скасувати лобі", callback_data=f"party_cancel_lobby:{lobby_id}"))
        
    return builder.as_markup()

# === КЛАВІАТУРИ ДЛЯ РЕЄСТРАЦІЇ ТА ПРОФІЛЮ ===
# ... (решта коду файлу залишається без змін) ...
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
    builder.button(text="🔄 Профіль", callback_data="profile_update_basic")
    builder.button(text="📈 Статистика", callback_data="profile_add_stats")
    builder.button(text="🦸 Герої", callback_data="profile_add_heroes")
    builder.button(text="🗑️ Видалити", callback_data="profile_delete")
    builder.button(text="◀️ Назад", callback_data="profile_menu_collapse")
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