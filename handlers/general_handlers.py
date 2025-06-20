import html
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Deque, List
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update, CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

# Імпорти з проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH,
    BOT_NAMES, CONVERSATIONAL_COOLDOWN_SECONDS
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks
# --- ВИПРАВЛЕНІ ТА НОВІ ІМПОРТИ ---
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard,
    create_role_selection_keyboard,
    create_dynamic_lobby_keyboard  # <-- ОСЬ ВИПРАВЛЕННЯ!
)
from states.party_states import PartyCreation

# === СХОВИЩА ДАНИХ ДЛЯ КЕРУВАННЯ СТАНОМ ===
# ... (існуючі сховища chat_histories, chat_cooldowns) ...

# Словник для зберігання активних лобі.
# УВАГА: Це рішення для прототипу. Для production варто використовувати Redis або БД.
active_lobbies: Dict[str, Dict] = {}
ALL_ROLES: List[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]

# === РОЗДІЛЕННЯ РОУТЕРІВ ДЛЯ ЧИСТОТИ АРХІТЕКТУРИ ===
# Роутер для логіки паті, буде зареєстрований ПЕРШИМ
party_router = Router()
# Існуючий роутер для всіх інших загальних обробників
general_router = Router()


# --- ЛОГІКА СТВОРЕННЯ ПАТІ (FSM) ---

def get_lobby_message_text(lobby_data: dict) -> str:
    """Форматує текст повідомлення для лобі, генеруючи його на основі поточних даних."""
    leader_name = html.escape(lobby_data['leader_name'])
    role_emoji_map = {"Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙", "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"}
    
    players_list = []
    taken_roles = []
    for player_id, player_info in lobby_data['players'].items():
        role = player_info['role']
        name = html.escape(player_info['name'])
        emoji = role_emoji_map.get(role, "🔹")
        players_list.append(f"• {emoji} <b>{role}:</b> {name}")
        taken_roles.append(role)

    available_roles_list = [f"• {role_emoji_map.get(r, '🔹')} {r}" for r in ALL_ROLES if r not in taken_roles]
    header = f"🔥 <b>Збираємо паті на рейтинг!</b> 🔥\n\n<b>Ініціатор:</b> {leader_name}\n"
    players_section = "<b>Учасники:</b>\n" + "\n".join(players_list)
    
    available_section = "\n\n<b>Вільні ролі:</b>\n" + "\n".join(available_roles_list) if available_roles_list else "\n\n✅ <b>Команда зібрана!</b>"

    return f"{header}\n{players_section}{available_section}"

@party_router.message(F.text & F.func(lambda msg: re.search(r'\b(паті|пати|команду)\b', msg.text.lower()) and re.search(r'\b(збира|го|шукаю|+\?)\b', msg.text.lower())))
async def ask_for_party_creation(message: Message, state: FSMContext):
    """Перехоплює повідомлення про пошук паті, запускає FSM та запитує підтвердження."""
    await state.set_state(PartyCreation.confirm_creation)
    await message.reply("Бачу, ти хочеш зібрати команду. Допомогти тобі?", reply_markup=create_party_confirmation_keyboard())

@party_router.callback_query(PartyCreation.confirm_creation, F.data == "party_create_cancel")
async def cancel_party_creation(callback: CallbackQuery, state: FSMContext):
    """Обробляє відмову від допомоги у створенні паті."""
    await state.clear()
    await callback.message.edit_text("Гаразд. Якщо передумаєш - звертайся! 😉")
    await callback.answer()

@party_router.callback_query(PartyCreation.confirm_creation, F.data == "party_create_confirm")
async def prompt_for_role(callback: CallbackQuery, state: FSMContext):
    """Після підтвердження, запитує у ініціатора його роль."""
    await state.set_state(PartyCreation.select_role)
    await callback.message.edit_text("Чудово! Оберіть свою роль, щоб інші знали, кого ви шукаєте:", reply_markup=create_role_selection_keyboard(ALL_ROLES))
    await callback.answer()

@party_router.callback_query(PartyCreation.select_role, F.data.startswith("party_role_select_"))
async def create_party_lobby(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Фінальний крок: створює лобі, додає ініціатора, публікує повідомлення."""
    user = callback.from_user
    selected_role = callback.data.split("party_role_select_")[1]
    lobby_id = str(callback.message.message_id)

    # КЛЮЧОВЕ ВИПРАВЛЕННЯ: Ініціатор одразу додається до списку гравців
    lobby_data = {
        "leader_id": user.id,
        "leader_name": user.first_name,
        "players": {user.id: {"name": user.first_name, "role": selected_role}},
        "chat_id": callback.message.chat.id
    }
    active_lobbies[lobby_id] = lobby_data
    logger.info(f"Створено нове лобі {lobby_id} ініціатором {user.first_name} (ID: {user.id}) з роллю {selected_role}")

    message_text = get_lobby_message_text(lobby_data)
    keyboard = create_dynamic_lobby_keyboard(lobby_id, user.id, lobby_data)
    
    await callback.message.edit_text(message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer(f"Ви зайняли роль: {selected_role}")
    await state.clear()

# --- ІСНУЮЧІ ОБРОБНИКИ (без змін, просто перенесені під `general_router`) ---

@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    # ... (код cmd_start без змін)
    pass

@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    # ... (код cmd_go без змін)
    pass

@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    # ... (код handle_trigger_messages без змін)
    pass

async def error_handler(event: types.ErrorEvent, bot: Bot):
    # ... (код error_handler без змін)
    pass


def register_general_handlers(dp: Dispatcher):
    """
    Реєструє всі обробники в головному диспетчері.
    Дуже важливо дотримуватися порядку: специфічні роутери (паті) перед загальними.
    """
    dp.include_router(party_router)  # <-- Спочатку реєструємо обробник паті
    dp.include_router(general_router) # <-- Потім загальні обробники
    logger.info("Обробники для паті (FSM) та загальні тригери успішно зареєстровано.")
