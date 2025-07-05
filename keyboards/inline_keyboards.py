"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Розширено для підтримки покрокового створення паті (FSM) та реєстрації.
🆕 v3.8: Оновлено назву режиму "Бравл" на "Режим бою".
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

# ОНОВЛЕНІ КОРОТКІ РОЛІ ДЛЯ КРАЩОГО UX
ALL_ROLES: List[str] = ["EXP", "ЛІС", "МІД", "АДК", "РОУМ"]

# --- 🔄 ОНОВЛЕНІ КЛАВІАТУРИ ДЛЯ FSM СТВОРЕННЯ ПАТІ ---

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для підтвердження наміру користувача створити паті.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так", callback_data="party_start_creation")
    builder.button(text="❌ Ні", callback_data="party_cancel_creation")
    builder.button(text="ℹ️ Інфо", callback_data="party_show_info")
    builder.adjust(2, 1)
    return builder.as_markup()

def create_party_info_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру з кнопкою "Назад" для екрану довідки.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_confirmation")
    return builder.as_markup()

def create_game_mode_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору режиму гри (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Ранк", callback_data="party_set_mode:Ranked")
    builder.button(text="🎮 Класика", callback_data="party_set_mode:Classic")
    builder.button(text="⚔️ Режим бою", callback_data="party_set_mode:Brawl") # Оновлено
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_confirmation")
    builder.adjust(2) 
    return builder.as_markup()

def create_party_size_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору розміру паті (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Дуо", callback_data="party_set_size:2")
    builder.button(text="👥 Тріо", callback_data="party_set_size:3")
    builder.button(text="👥 Фулл", callback_data="party_set_size:5")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_game_mode")
    builder.adjust(2, 2)
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str], lobby_id: str) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору ролі (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}
    
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
    
    if lobby_id == "initial":
        builder.button(text="◀️ Назад", callback_data="party_step_back:to_party_size")
        builder.adjust(2)
    else:
        builder.adjust(2, 1) # Для 5 ролей буде 2, 2, 1
        builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data=f"party_cancel_join:{lobby_id}"))
        
    return builder.as_markup()

def create_required_roles_keyboard(
    available_roles: List[str], 
    selected_roles: List[str], 
    num_to_select: int
) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору бажаних ролей з мультиселектом (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}

    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        text = f"✅ {emoji} {role}" if role in selected_roles else f"{emoji} {role}"
        builder.button(text=text, callback_data=f"party_req_role:{role}")

    builder.adjust(2)

    # Кнопки управління додаються окремо
    action_buttons = []
    if len(selected_roles) == num_to_select:
        action_buttons.append(InlineKeyboardButton(text="✅ Готово", callback_data="party_confirm_roles"))
    else:
        remaining = num_to_select - len(selected_roles)
        action_buttons.append(InlineKeyboardButton(text=f"⏳ Ще {remaining}", callback_data="party_dummy_button"))
    
    action_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data="party_step_back:to_leader_role"))
    builder.row(*action_buttons)
    
    return builder.as_markup()

def create_lobby_keyboard(lobby_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для активного лобі (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    lobby_state = lobby_data.get("state", "open")
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}
    
    if lobby_state == "joining":
        taken_roles = [p["role"] for p in lobby_data["players"].values()]
        required_roles = lobby_data.get('required_roles', [])
        
        if required_roles:
            available_roles = [r for r in required_roles if r not in taken_roles]
        else:
            available_roles = [r for r in ALL_ROLES if r not in taken_roles]
        
        for role in available_roles:
            emoji = role_emoji_map.get(role, "🔹")
            builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
        
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data=f"party_cancel_join:{lobby_id}"))

    else: # lobby_state == "open"
        players = lobby_data.get("players", {})
        party_size = lobby_data.get("party_size", 5)
        
        if len(players) < party_size:
            builder.button(text="➕ Увійти", callback_data=f"party_join:{lobby_id}")
        
        builder.button(text="❌ Вийти", callback_data=f"party_leave:{lobby_id}")
        builder.button(text="🚫 Закрити", callback_data=f"party_cancel_lobby:{lobby_id}")
        
        builder.adjust(2, 1) # Завжди буде 2 або 3 кнопки, цей adjust ідеально підходить
        
    return builder.as_markup()

# === КЛАВІАТУРИ ДЛЯ РЕЄСТРАЦІЇ ТА ПРОФІЛЮ ===

def create_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Створює початкову, компактну клавіатуру для меню профілю (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚙️ Налаштувати", callback_data="profile_menu_expand"),
        InlineKeyboardButton(text="🚪 Вийти", callback_data="profile_menu_close")
    )
    return builder.as_markup()

def create_expanded_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Створює розширену клавіатуру для меню профілю (2 колонки).
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
    Клавіатура для підтвердження видалення профілю (2 колонки).
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так", callback_data="delete_confirm_yes")
    builder.button(text="❌ Ні", callback_data="delete_confirm_no")
    builder.adjust(2)
    return builder.as_markup()