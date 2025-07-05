"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Розширено для підтримки покрокового створення паті (FSM) та реєстрації.
🆕 v3.1: Оптимізовані ролі та компактні кнопки.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict, Optional

# 🆕 ОНОВЛЕНІ КОРОТКІ РОЛІ ДЛЯ КРАЩОГО UX
ALL_ROLES: List[str] = ["EXP", "ЛІС", "МІД", "АДК", "РОУМ"]

# --- 🔄 ОНОВЛЕНІ КЛАВІАТУРИ ДЛЯ FSM СТВОРЕННЯ ПАТІ ---

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для підтвердження наміру користувача створити паті.
    🆕 Компактні кнопки для кращого UX.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅", callback_data="party_start_creation")
    builder.button(text="❌", callback_data="party_cancel_creation")
    builder.button(text="ℹ️ Інфо", callback_data="party_show_info")
    builder.adjust(2, 1)  # Макет: 2 кнопки в першому ряду, 1 - у другому
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
    Створює оптимізовану клавіатуру для вибору режиму гри.
    🆕 Скорочені назви для компактності.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Ранк", callback_data="party_set_mode:Ranked")
    builder.button(text="🎮 Класика", callback_data="party_set_mode:Classic")
    builder.button(text="⚔️ Бравл", callback_data="party_set_mode:Brawl")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_confirmation")
    builder.adjust(3, 1)  # 3 режими в ряд для компактності
    return builder.as_markup()

def create_party_size_keyboard() -> InlineKeyboardMarkup:
    """
    Створює компактну клавіатуру для вибору розміру паті.
    🆕 Без зайвих цифр у дужках.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Дуо", callback_data="party_set_size:2")
    builder.button(text="👥 Тріо", callback_data="party_set_size:3")
    builder.button(text="👥 Фулл", callback_data="party_set_size:5")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_game_mode")
    builder.adjust(3, 1)  # 3 розміри в ряд
    return builder.as_markup()

def create_role_selection_keyboard(available_roles: List[str], lobby_id: str) -> InlineKeyboardMarkup:
    """
    Створює оптимізовану клавіатуру для вибору ролі.
    🆕 Нові короткі ролі та гнучка сітка.
    """
    builder = InlineKeyboardBuilder()
    
    # 🆕 ОНОВЛЕНА МАПА ЕМОДЖІ ДЛЯ НОВИХ РОЛЕЙ
    role_emoji_map = {
        "EXP": "⚔️",      # Experience Lane (Боєць)
        "ЛІС": "🌳",      # Jungle (Лісник)
        "МІД": "🧙",      # Mid Lane (Маг)
        "АДК": "🏹",      # ADC/Gold Lane (Стрілець)
        "РОУМ": "🛡️"     # Roam/Support (Танк/Підтримка)
    }
    
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
    
    if lobby_id == "initial":
        builder.button(text="◀️ Назад", callback_data="party_step_back:to_party_size")
        # Гнучка сітка: 3-2 для 5 ролей, 2-2-1 для інших
        if len(available_roles) == 5:
            builder.adjust(3, 2, 1)
        else:
            builder.adjust(2, 1)
    else:
        # Для активного лобі
        if len(available_roles) == 5:
            builder.adjust(3, 2)
        else:
            builder.adjust(2)
        builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data=f"party_cancel_join:{lobby_id}"))
        
    return builder.as_markup()

def create_required_roles_keyboard(
    available_roles: List[str], 
    selected_roles: List[str], 
    num_to_select: int
) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для вибору бажаних ролей з мультиселектом.
    🆕 Оновлена для нових ролей.
    """
    builder = InlineKeyboardBuilder()
    
    # 🆕 ОНОВЛЕНА МАПА ЕМОДЖІ
    role_emoji_map = {
        "EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", 
        "АДК": "🏹", "РОУМ": "🛡️"
    }

    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        text = f"✅ {emoji} {role}" if role in selected_roles else f"{emoji} {role}"
        builder.button(text=text, callback_data=f"party_req_role:{role}")

    # Статус вибору
    if len(selected_roles) == num_to_select:
        builder.button(text="✅ Готово", callback_data="party_confirm_roles")
    else:
        remaining = num_to_select - len(selected_roles)
        builder.button(text=f"⏳ Ще {remaining}", callback_data="party_dummy_button")

    builder.button(text="◀️ Назад", callback_data="party_step_back:to_leader_role")
    
    # Гнучка сітка для ролей
    if len(available_roles) == 4:
        builder.adjust(2, 2, 2, 1)  # 2x2 ролі, статус, назад
    else:
        builder.adjust(3, 2, 1)
    
    return builder.as_markup()

def create_lobby_keyboard(lobby_id: int, lobby_data: Dict) -> InlineKeyboardMarkup:
    """
    Створює оптимізовану клавіатуру для активного лобі.
    🆕 Компактні кнопки та нові ролі.
    """
    builder = InlineKeyboardBuilder()
    lobby_state = lobby_data.get("state", "open")
    
    # 🆕 ОНОВЛЕНА МАПА ЕМОДЖІ
    role_emoji_map = {
        "EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", 
        "АДК": "🏹", "РОУМ": "🛡️"
    }
    
    if lobby_state == "joining":
        # Логіка вибору ролей при приєднанні
        taken_roles = [p["role"] for p in lobby_data["players"].values()]
        required_roles = lobby_data.get('required_roles', [])
        
        if required_roles:
            available_roles = [r for r in required_roles if r not in taken_roles]
        else:
            available_roles = [r for r in ALL_ROLES if r not in taken_roles]
        
        for role in available_roles:
            emoji = role_emoji_map.get(role, "🔹")
            builder.button(text=f"{emoji} {role}", callback_data=f"party_select_role:{lobby_id}:{role}")
        
        # Гнучка сітка для ролей
        if len(available_roles) == 5:
            builder.adjust(3, 2)
        elif len(available_roles) == 4:
            builder.adjust(2, 2)
        else:
            builder.adjust(2)
            
        builder.row(InlineKeyboardButton(text="❌ Скасувати", callback_data=f"party_cancel_join:{lobby_id}"))

    else: # lobby_state == "open"
        # Кнопки управління лобі
        players = lobby_data.get("players", {})
        party_size = lobby_data.get("party_size", 5)
        
        action_buttons = []
        if len(players) < party_size:
            action_buttons.append(InlineKeyboardButton(text="➕ Увійти", callback_data=f"party_join:{lobby_id}"))
        
        action_buttons.append(InlineKeyboardButton(text="❌ Вийти", callback_data=f"party_leave:{lobby_id}"))
        
        if action_buttons:
            builder.row(*action_buttons)
        
        builder.row(InlineKeyboardButton(text="🚫 Закрити", callback_data=f"party_cancel_lobby:{lobby_id}"))
        
    return builder.as_markup()

# === КЛАВІАТУРИ ДЛЯ РЕЄСТРАЦІЇ ТА ПРОФІЛЮ (без змін) ===

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