"""
Модуль для створення всіх інлайн-клавіатур, що використовуються в боті.
Включає:
- клавіатури для покрокового створення паті (FSM)
- інтерактивне меню користувача з однокнопковим режимом та розгорнутим оглядом
- навігацію каруселлю профілю
- підтвердження видалення профілю
- ❗️ НОВЕ: Динамічне меню для налаштувань м'юту.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ❗️ НОВИЙ ІМПОРТ
from database.models import UserSettings

# Короткі коди ролей для паті
ALL_ROLES: list[str] = ["EXP", "ЛІС", "МІД", "АДК", "РОУМ"]

# -------------------------------------------------------------------
# Клавіатури для створення паті (FSM)
# -------------------------------------------------------------------

def create_party_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура для підтвердження створення паті:
    | ✅ Так | ❌ Ні | ℹ️ Інфо |
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Так", callback_data="party_start_creation")
    builder.button(text="❌ Ні", callback_data="party_cancel_creation")
    builder.button(text="ℹ️ Інфо", callback_data="party_show_info")
    builder.adjust(2, 1)
    return builder.as_markup()

def create_party_info_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура для екрану довідки про створення паті:
    | ◀️ Назад |
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_confirmation")
    return builder.as_markup()

def create_game_mode_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура для вибору режиму гри:
    | 🏆 Ранк | 🕹️ Класика |
    | ⚔️ Режим бою | ◀️ Назад |
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🏆 Ранк", callback_data="party_set_mode:Ranked")
    builder.button(text="🕹️ Класика", callback_data="party_set_mode:Classic")
    builder.button(text="⚔️ Режим бою", callback_data="party_set_mode:Brawl")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_confirmation")
    builder.adjust(2)
    return builder.as_markup()

def create_party_size_keyboard() -> InlineKeyboardMarkup:
    """
    Клавіатура для вибору розміру паті:
    | 👥 Дуо | 👥 Тріо |
    | 👥 Фулл | ◀️ Назад |
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Дуо", callback_data="party_set_size:2")
    builder.button(text="👥 Тріо", callback_data="party_set_size:3")
    builder.button(text="👥 Фулл", callback_data="party_set_size:5")
    builder.button(text="◀️ Назад", callback_data="party_step_back:to_game_mode")
    builder.adjust(2, 2)
    return builder.as_markup()

def create_role_selection_keyboard(
    available_roles: list[str],
    lobby_id: str
) -> InlineKeyboardMarkup:
    """
    Клавіатура для вибору ролі:
    - Доступні ролі розміщуються у два стовпці.
    - Якщо lobby_id == "initial", додається кнопка ◀️ Назад.
    - Інакше під кнопками зʼявляється кнопка ❌ Скасувати.
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        builder.button(
            text=f"{emoji} {role}",
            callback_data=f"party_select_role:{lobby_id}:{role}"
        )
    if lobby_id == "initial":
        builder.button(text="◀️ Назад", callback_data="party_step_back:to_party_size")
        builder.adjust(2)
    else:
        builder.adjust(2, 1)
        builder.row(
            InlineKeyboardButton(
                text="❌ Скасувати",
                callback_data=f"party_cancel_join:{lobby_id}"
            )
        )
    return builder.as_markup()

def create_required_roles_keyboard(
    available_roles: list[str],
    selected_roles: list[str],
    num_to_select: int
) -> InlineKeyboardMarkup:
    """
    Клавіатура для мультивибору бажаних ролей:
    - Перелік ролей у 2 колонки, відмічені обрані.
    - Під списком кнопка ✅ Готово або індикатор ⏳ Ще N.
    - Кнопка ◀️ Назад до вибору лідера.
    """
    builder = InlineKeyboardBuilder()
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}
    for role in available_roles:
        emoji = role_emoji_map.get(role, "🔹")
        if role in selected_roles:
            text = f"✅ {emoji} {role}"
        else:
            text = f"{emoji} {role}"
        builder.button(text=text, callback_data=f"party_req_role:{role}")
    builder.adjust(2)

    action_buttons = []
    if len(selected_roles) == num_to_select:
        action_buttons.append(
            InlineKeyboardButton(text="✅ Готово", callback_data="party_confirm_roles")
        )
    else:
        remaining = num_to_select - len(selected_roles)
        action_buttons.append(
            InlineKeyboardButton(text=f"⏳ Ще {remaining}", callback_data="party_dummy_button")
        )
    action_buttons.append(
        InlineKeyboardButton(text="◀️ Назад", callback_data="party_step_back:to_leader_role")
    )
    builder.row(*action_buttons)
    return builder.as_markup()

def create_lobby_keyboard(
    lobby_id: int,
    lobby_data: dict
) -> InlineKeyboardMarkup:
    """
    Клавіатура для активного лобі:
    - Якщо стан 'joining', показує кнопки доступних ролей і ❌ Скасувати.
    - Якщо 'open', показує ➕ Увійти, ❌ Вийти, 🚫 Закрити.
    """
    builder = InlineKeyboardBuilder()
    lobby_state = lobby_data.get("state", "open")
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}

    if lobby_state == "joining":
        taken = [p["role"] for p in lobby_data["players"].values()]
        required = lobby_data.get("required_roles", [])
        if required:
            available = [r for r in required if r not in taken]
        else:
            available = [r for r in ALL_ROLES if r not in taken]
        for role in available:
            emoji = role_emoji_map.get(role, "🔹")
            builder.button(
                text=f"{emoji} {role}",
                callback_data=f"party_select_role:{lobby_id}:{role}"
            )
        builder.adjust(2)
        builder.row(
            InlineKeyboardButton(
                text="❌ Скасувати",
                callback_data=f"party_cancel_join:{lobby_id}"
            )
        )
    else:
        players = lobby_data.get("players", {})
        size = lobby_data.get("party_size", 5)
        if len(players) < size:
            builder.button(text="➕ Увійти", callback_data=f"party_join:{lobby_id}")
        builder.button(text="❌ Вийти", callback_data=f"party_leave:{lobby_id}")
        builder.button(text="🚫 Закрити", callback_data=f"party_cancel_lobby:{lobby_id}")
        builder.adjust(2, 1)

    return builder.as_markup()

# -------------------------------------------------------------------
# Клавіатури для профілю користувача
# -------------------------------------------------------------------

def create_profile_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Початковий однокнопковий режим профілю:
    | 📋 Меню |
    При натисканні відкриває розгорнуте меню з оглядом дій.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Меню", callback_data="profile_show_menu")
    )
    return builder.as_markup()

def create_profile_menu_overview_keyboard(
    current_page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """
    Розгорнуте інтерактивне меню профілю.
    1. Навігація каруселлю, тільки стрілки, якщо більше однієї сторінки:
       | ◀️ | ▶️ |
    2. Дії:
       | 🔄 Профіль | 📈 Статистика |
       | 🦸 Герої   | 🖼️ Аватар      |
       | 🗑️ Видалити | ◀️ Приховати меню |
    """
    builder = InlineKeyboardBuilder()

    # Додаємо стрілки навігації лише коли сторінок більше однієї
    if total_pages > 1:
        prev_disabled = current_page <= 1
        next_disabled = current_page >= total_pages
        # Кнопка "назад"
        builder.button(
            text="◀️",
            callback_data=f"profile_prev_page:{current_page-1}",
            disabled=prev_disabled
        )
        # Кнопка "вперед"
        builder.button(
            text="▶️",
            callback_data=f"profile_next_page:{current_page+1}",
            disabled=next_disabled
        )
        # Розташувати обидві в один ряд
        builder.adjust(2)

    # Основні дії користувача
    builder.button(text="🔄 Профіль",     callback_data="profile_update_basic")
    builder.button(text="📈 Статистика", callback_data="profile_update_stats")
    builder.button(text="🦸 Герої",       callback_data="profile_update_heroes")
    builder.button(text="🖼️ Аватар",     callback_data="profile_update_avatar")
    builder.button(text="🗑️ Видалити",   callback_data="profile_delete")
    builder.button(text="◀️ Закрити",    callback_data="profile_hide_menu")
    # Викладка у два стовпці
    builder.adjust(2, 2, 2)

    return builder.as_markup()

# -------------------------------------------------------------------
# Підтвердження видалення профілю
# -------------------------------------------------------------------

def create_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Підтвердження дії видалення профілю:
    | ✅ Так | ❌ Ні |
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Так", callback_data="delete_confirm_yes"),
        InlineKeyboardButton(text="❌ Ні", callback_data="delete_confirm_no")
    )
    return builder.as_markup()

# -------------------------------------------------------------------
# ❗️ НОВА СЕКЦІЯ: Клавіатури для налаштувань користувача
# -------------------------------------------------------------------

def create_mute_settings_keyboard(settings: UserSettings) -> InlineKeyboardMarkup:
    """
    Створює динамічну клавіатуру для керування налаштуваннями м'юту.
    
    Args:
        settings: Об'єкт UserSettings з поточними налаштуваннями.
        
    Returns:
        Інлайн-клавіатура для меню налаштувань.
    """
    builder = InlineKeyboardBuilder()

    # Словник: ключ_налаштування -> (Текст для кнопки, Емодзі)
    options = {
        "chat": ("Спілкування", "💬"),
        "vision": ("Аналіз фото", "📸"),
        "party": ("Збір паті", "🎮"),
    }

    for key, (text, emoji) in options.items():
        # Отримуємо поточний статус (True/False) для ключа
        is_muted = getattr(settings, f"mute_{key}", False)
        
        # Формуємо текст кнопки
        status_emoji = "❌" if is_muted else "✅"
        button_text = f"{status_emoji} {text}"
        
        # Формуємо callback_data
        callback_data = f"toggle_mute:{key}"
        
        builder.button(text=button_text, callback_data=callback_data)

    # Додаємо кнопку для закриття меню
    builder.row(InlineKeyboardButton(text="👌 Готово", callback_data="close_settings_menu"))
    
    # Розташовуємо кнопки налаштувань в один стовпець
    builder.adjust(1, 1, 1, 1)
    
    return builder.as_markup()
