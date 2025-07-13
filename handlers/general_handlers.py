"""
Головний модуль обробників загального призначення.

Цей файл містить всю логіку для:
- Обробки стартових команд (/start, /go, /search).
- Адаптивної відповіді на тригерні фрази в чаті.
- Покрокового створення ігрового лобі (паті) з використанням FSM.
- Універсального розпізнавання та обробки зображень.
- Глобальної обробки помилок.
- Встановлення списку команд для меню бота.

Архітектура побудована на двох роутерах для керування пріоритетами:
1. `party_router`: Перехоплює специфічні запити на створення паті.
2. `general_router`: Обробляє всі інші загальні команди, повідомлення та зображення.
"""
import html
import logging
import re
import time
import base64
import io
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Deque, List
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update, CallbackQuery, PhotoSize, BotCommand, BotCommandScopeDefault
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from openai import RateLimitError # 👈 Новий імпорт

# Імпорти з нашого проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH,
    BOT_NAMES, CONVERSATIONAL_COOLDOWN_SECONDS,
    VISION_AUTO_RESPONSE_ENABLED, VISION_RESPONSE_COOLDOWN_SECONDS, 
    VISION_MAX_IMAGE_SIZE_MB, VISION_CONTENT_EMOJIS
)
# Імпортуємо сервіси та утиліти
from services.openai_service import MLBBChatGPT
from services.gemini_service import GeminiSearch
from services.research_service import MLBBDeepResearch
from utils.message_utils import send_message_in_chunks
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard,
    create_role_selection_keyboard,
    create_lobby_keyboard,
    ALL_ROLES,
    create_game_mode_keyboard,
    create_party_size_keyboard,
    create_required_roles_keyboard,
    create_party_info_keyboard 
)
# 🧠 ІМПОРТУЄМО ФУНКЦІЇ ДЛЯ РОБОТИ З БД ТА НОВИМИ ШАРАМИ ПАМ'ЯТІ
from database.crud import get_user_by_telegram_id
from utils.session_memory import SessionData, load_session, save_session
from utils.cache_manager import load_user_cache, save_user_cache


# === 🔄 ОНОВЛЕННЯ СТАНІВ FSM ===
class PartyCreationFSM(StatesGroup):
    """Розширені стани для покрокового процесу створення паті."""
    waiting_for_confirmation = State()
    waiting_for_game_mode = State()
    waiting_for_party_size = State()
    waiting_for_role_selection = State()
    waiting_for_required_roles = State()


# === СХОВИЩА ДАНИХ У ПАМ'ЯТІ ===
chat_cooldowns: Dict[int, float] = {}
vision_cooldowns: Dict[int, float] = {}
active_lobbies: Dict[int, Dict] = {} 

# 🧠 Визначаємо тригери для завантаження повного профілю
PERSONALIZATION_TRIGGERS = [
    "мій ранг", "мої герої", "моїх героїв", "мої улюблені",
    "мій вінрейт", "моя стата", "мій профіль", "про мене"
]

# === ІНІЦІАЛІЗАЦІЯ РОУТЕРІВ ТА КЛІЄНТІВ ===
party_router = Router()
general_router = Router()
# 🚀 Ініціалізуємо GPT клієнт для використання в різних обробниках
gpt_client = MLBBChatGPT(OPENAI_API_KEY)


# === ФУНКЦІЯ ДЛЯ ВСТАНОВЛЕННЯ КОМАНД БОТА ===
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🏁 Перезапустити бота"),
        BotCommand(command="profile", description="👤 Мій профіль (реєстрація/оновлення)"),
        BotCommand(command="go", description="💬 Задати питання AI-помічнику"),
        BotCommand(command="search", description="🔍 Пошук новин та оновлень"),
        BotCommand(command="research", description="🔬 Глибокий аналіз теми"), # Нова команда
        BotCommand(command="analyzeprofile", description="📸 Аналіз скріншота профілю"),
        BotCommand(command="analyzestats", description="📊 Аналіз скріншота статистики"),
        BotCommand(command="help", description="❓ Допомога та інфо"),
    ]
    try:
        await bot.set_my_commands(commands, BotCommandScopeDefault())
        logger.info("✅ Список команд бота успішно оновлено.")
    except Exception as e:
        logger.error(f"Помилка під час оновлення команд бота: {e}", exc_info=True)

# === ДОПОМІЖНІ ФУНКЦІЇ ===
def get_user_display_name(user: Optional[types.User]) -> str:
    if not user:
        return "друже"
    if user.first_name and user.first_name.strip():
        return html.escape(user.first_name.strip())
    elif user.username and user.username.strip():
        return html.escape(user.username.strip())
    else:
        return "друже"

def is_party_request_message(message: Message) -> bool:
    if not message.text:
        return False
    try:
        text_lower = message.text.lower()
        has_party_keywords = re.search(r'\b(паті|пати|команду)\b', text_lower) is not None
        has_action_keywords = re.search(r'\b(збир|го|шука|грат|зібра)\w*\b|\+', text_lower) is not None
        return has_party_keywords and has_action_keywords
    except (AttributeError, TypeError) as e:
        logger.warning(f"Помилка при перевірці party request: {e}")
        return False

def get_lobby_message_text(lobby_data: dict, joining_user_name: Optional[str] = None) -> str:
    """
    Створює розширений та візуально привабливий текст для лобі-повідомлення.
    🆕 v3.8: Оновлено назву режиму "Бравл" на "Режим бою".
    """
    leader_name = html.escape(lobby_data['leader_name'])
    game_mode = lobby_data.get('game_mode', 'Ranked')
    party_size = lobby_data.get('party_size', 5)
    
    game_mode_map = {"Ranked": "🏆 Рейтинг", "Classic": "🕹️ Класика", "Brawl": "⚔️ Режим бою"} # Оновлено
    mode_display = game_mode_map.get(game_mode, game_mode)
    
    role_emoji_map = {
        "EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", 
        "АДК": "🏹", "РОУМ": "🛡️"
    }
    
    players_list = []
    taken_roles = [player_info['role'] for player_info in lobby_data['players'].values()]
    
    sorted_players = sorted(lobby_data['players'].items(), key=lambda item: ALL_ROLES.index(item[1]['role']))

    for player_id, player_info in sorted_players:
        role = player_info['role']
        name = html.escape(player_info['name'])
        emoji = role_emoji_map.get(role, "🔹")
        players_list.append(f"  {emoji} <b>{role}:</b> {name}")

    available_slots_count = party_size - len(players_list)
    
    filled_dots = "🟢" * len(players_list)
    empty_dots = "⚪" * available_slots_count
    progress_bar = filled_dots + empty_dots

    text_parts = []
    text_parts.append(f"<b>{mode_display}</b>")
    text_parts.append(f"<b>🧑‍🤝‍🧑 ЗБІР КОМАНДИ</b>")
    text_parts.append("─────────────────")

    text_parts.append(f"👑 <b>Лідер:</b> {leader_name}")
    text_parts.append(f"📊 <b>Прогрес:</b> {progress_bar} ({len(players_list)}/{party_size})")

    if players_list:
        text_parts.append("\n👥 <b>СКЛАД КОМАНДИ:</b>")
        text_parts.extend(players_list)

    if lobby_data.get('state') == 'joining' and joining_user_name:
        text_parts.append(f"\n⏳ <b>{html.escape(joining_user_name)}, оберіть свою роль...</b>")
    elif available_slots_count > 0:
        required_roles = lobby_data.get('required_roles', [])
        if required_roles:
            available_roles = [r for r in required_roles if r not in taken_roles]
        else:
            available_roles = [r for r in ALL_ROLES if r not in taken_roles]
        
        section_title = "🔍 <b>ШУКАЄМО</b>" if required_roles else "🆓 <b>ДОСТУПНО</b>"
        text_parts.append(f"\n{section_title}:")
        
        available_roles_lines = [f"  {role_emoji_map.get(r, '🔹')} {r}" for r in available_roles]
        text_parts.extend(available_roles_lines)
        
        text_parts.append("\n💬 <i>Натисни кнопку, щоб приєднатися!</i>")
    else:
        text_parts.append("\n\n✅ <b>КОМАНДА ГОТОВА! ПОГНАЛИ! 🚀</b>")
        
    return f"<blockquote>" + "\n".join(text_parts) + "</blockquote>"


# === 🔄 ОНОВЛЕНА ЛОГІКА СТВОРЕННЯ ПАТІ (FSM) ===
@party_router.message(F.text & F.func(is_party_request_message))
async def ask_for_party_creation(message: Message, state: FSMContext):
    user_name = get_user_display_name(message.from_user)
    logger.info(f"Виявлено запит на створення паті від {user_name}: '{message.text}'")
    await state.set_state(PartyCreationFSM.waiting_for_confirmation)
    sent_message = await message.reply(
        "👋 Привіт! Бачу, ти збираєш команду.\n"
        "Допомогти тобі створити інтерактивне лобі?",
        reply_markup=create_party_confirmation_keyboard()
    )
    await state.update_data(last_message_id=sent_message.message_id, initiator_id=message.from_user.id)

@party_router.callback_query(F.data == "party_show_info")
async def show_party_info(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return

    info_text = (
        "ℹ️ <b>Довідка по функції 'Зібрати Паті'</b>\n\n"
        "Ця функція допоможе тобі швидко організувати команду для гри в Mobile Legends.\n\n"
        "<b>Як це працює:</b>\n"
        "1. Я покроково запитаю тебе про режим гри (Рейтинг, Класика), кількість гравців та бажані ролі.\n"
        "2. Після налаштування я створю лобі-повідомлення в чаті, до якого зможуть приєднатися інші гравці.\n"
        "3. Учасники зможуть обрати вільну роль і приєднатись, а ти, як лідер, зможеш закрити лобі.\n\n"
        "Просто натисни '✅', щоб почати! 👍"
    )
    await callback.message.edit_text(info_text, reply_markup=create_party_info_keyboard())
    await callback.answer()

@party_router.callback_query(F.data == "party_cancel_creation")
async def cancel_party_creation(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    await state.clear()
    await callback.message.edit_text("Гаразд, скасовано. Якщо передумаєш - звертайся! 😉")
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_confirmation, F.data == "party_start_creation")
async def prompt_for_game_mode(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return

    await state.set_state(PartyCreationFSM.waiting_for_game_mode)
    await callback.message.edit_text(
        "🎮 <b>Крок 1/3: Режим гри</b>\n\n"
        "Чудово! Спочатку вибери, де будемо перемагати:", 
        reply_markup=create_game_mode_keyboard()
    )
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_game_mode, F.data.startswith("party_set_mode:"))
async def prompt_for_party_size(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    game_mode = callback.data.split(":")[-1]
    await state.update_data(game_mode=game_mode)
    await state.set_state(PartyCreationFSM.waiting_for_party_size)
    await callback.message.edit_text(
        "👥 <b>Крок 2/3: Розмір команди</b>\n\n"
        "Тепер вибери, скільки гравців ти шукаєш:", 
        reply_markup=create_party_size_keyboard()
    )
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_party_size, F.data.startswith("party_set_size:"))
async def prompt_for_leader_role(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return

    party_size = int(callback.data.split(":")[-1])
    await state.update_data(party_size=party_size)
    await state.set_state(PartyCreationFSM.waiting_for_role_selection)
    await callback.message.edit_text(
        "🦸 <b>Крок 3/3: Твоя роль</b>\n\n"
        "Майже готово! Вибери свою роль у цій команді:", 
        reply_markup=create_role_selection_keyboard(ALL_ROLES, "initial")
    )
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_role_selection, F.data.startswith("party_select_role:initial:"))
async def handle_leader_role_selection(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    selected_role = callback.data.split(":")[-1]
    await state.update_data(leader_role=selected_role)
    
    state_data = await state.get_data()
    party_size = state_data.get("party_size", 5)
    
    if party_size < 5:
        await state.set_state(PartyCreationFSM.waiting_for_required_roles)
        num_to_select = party_size - 1
        available_for_selection = [r for r in ALL_ROLES if r != selected_role]
        
        await state.update_data(selected_required_roles=[], num_to_select=num_to_select)
        
        await callback.message.edit_text(
            f"🔍 <b>Фінальний крок: Пошук ролей</b>\n\n"
            f"Тепер вибери <b>{num_to_select}</b> роль(і), яку(і) ти шукаєш:",
            reply_markup=create_required_roles_keyboard(available_for_selection, [], num_to_select)
        )
    else:
        await create_party_lobby(callback, state, bot)

@party_router.callback_query(PartyCreationFSM.waiting_for_required_roles, F.data.startswith("party_req_role:"))
async def handle_required_role_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return

    role = callback.data.split(":")[-1]
    selected = data.get("selected_required_roles", [])
    num_to_select = data.get("num_to_select", 1)
    leader_role = data.get("leader_role")
    
    if role in selected:
        selected.remove(role)
    else:
        if len(selected) < num_to_select:
            selected.append(role)
        else:
            await callback.answer(f"Можна вибрати лише {num_to_select} ролі.", show_alert=True)
            return

    await state.update_data(selected_required_roles=selected)
    
    available_for_selection = [r for r in ALL_ROLES if r != leader_role]
    await callback.message.edit_reply_markup(
        reply_markup=create_required_roles_keyboard(available_for_selection, selected, num_to_select)
    )
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_required_roles, F.data == "party_confirm_roles")
async def confirm_required_roles_and_create_lobby(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    await create_party_lobby(callback, state, bot)

async def create_party_lobby(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not callback.message: return
    user = callback.from_user
    state_data = await state.get_data()
    
    user_name = get_user_display_name(user)
    lobby_id = callback.message.message_id
    
    leader_role = state_data.get("leader_role")
    required_roles = state_data.get("selected_required_roles", [])
    
    lobby_data = {
        "leader_id": user.id,
        "leader_name": user_name,
        "players": {user.id: {"name": user_name, "role": leader_role}},
        "chat_id": callback.message.chat.id,
        "state": "open",
        "joining_user": None,
        "game_mode": state_data.get("game_mode", "Ranked"),
        "party_size": state_data.get("party_size", 5),
        "required_roles": required_roles
    }
    
    active_lobbies[lobby_id] = lobby_data
    
    message_text = get_lobby_message_text(lobby_data)
    keyboard = create_lobby_keyboard(lobby_id, lobby_data)
    
    await bot.edit_message_text(
        text=message_text,
        chat_id=callback.message.chat.id,
        message_id=lobby_id,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    
    logger.info(f"Створено лобі {lobby_id} ініціатором {user_name} (режим: {lobby_data['game_mode']}, розмір: {lobby_data['party_size']})")
    await callback.answer("Лобі створено!")
    await state.clear()

# === 🔄 ОНОВЛЕНІ ОБРОБНИКИ ДЛЯ КНОПОК "НАЗАД" ===
@party_router.callback_query(F.data == "party_step_back:to_confirmation")
async def step_back_to_confirmation(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    await state.set_state(PartyCreationFSM.waiting_for_confirmation)
    await callback.message.edit_text(
        "👋 Привіт! Бачу, ти збираєш команду.\n"
        "Допомогти тобі створити інтерактивне лобі?", 
        reply_markup=create_party_confirmation_keyboard()
    )
    await callback.answer()

@party_router.callback_query(F.data == "party_step_back:to_game_mode")
async def step_back_to_game_mode(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    await state.set_state(PartyCreationFSM.waiting_for_game_mode)
    await callback.message.edit_text(
        "🎮 <b>Крок 1/3: Режим гри</b>\n\n"
        "Чудово! Спочатку вибери, де будемо перемагати:", 
        reply_markup=create_game_mode_keyboard()
    )
    await callback.answer()

@party_router.callback_query(F.data == "party_step_back:to_party_size")
async def step_back_to_party_size(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    await state.set_state(PartyCreationFSM.waiting_for_party_size)
    await callback.message.edit_text(
        "👥 <b>Крок 2/3: Розмір команди</b>\n\n"
        "Тепер вибери, скільки гравців ти шукаєш:", 
        reply_markup=create_party_size_keyboard()
    )
    await callback.answer()

@party_router.callback_query(F.data == "party_step_back:to_leader_role")
async def step_back_to_leader_role(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if callback.from_user.id != data.get('initiator_id'):
        await callback.answer("Не чіпай, це не твоя кнопка! 😠", show_alert=True)
        return
        
    await state.set_state(PartyCreationFSM.waiting_for_role_selection)
    await callback.message.edit_text(
        "🦸 <b>Крок 3/3: Твоя роль</b>\n\n"
        "Майже готово! Вибери свою роль у цій команді:", 
        reply_markup=create_role_selection_keyboard(ALL_ROLES, "initial")
    )
    await callback.answer()

# === 🔄 ОНОВЛЕНА ЛОГІКА ВЗАЄМОДІЇ З ЛОБІ ===
@party_router.callback_query(F.data.startswith("party_join:"))
async def handle_join_request(callback: CallbackQuery, bot: Bot):
    lobby_id = int(callback.data.split(":")[-1])
    user = callback.from_user
    
    if lobby_id not in active_lobbies:
        await callback.answer("Цього лобі більше не існує.", show_alert=True)
        try: await callback.message.delete()
        except TelegramAPIError: pass
        return

    lobby_data = active_lobbies[lobby_id]
    
    if user.id in lobby_data["players"]:
        await callback.answer("Ти вже у цьому паті!", show_alert=True)
        return
        
    if len(lobby_data["players"]) >= lobby_data.get("party_size", 5):
        await callback.answer("Паті вже заповнено!", show_alert=True)
        return

    if lobby_data["state"] == "joining":
        await callback.answer("Хтось інший зараз приєднується. Зачекай.", show_alert=True)
        return
        
    lobby_data["state"] = "joining"
    lobby_data["joining_user"] = {"id": user.id, "name": get_user_display_name(user)}
    
    new_text = get_lobby_message_text(lobby_data, joining_user_name=get_user_display_name(user))
    new_keyboard = create_lobby_keyboard(lobby_id, lobby_data)

    await bot.edit_message_text(
        text=new_text,
        chat_id=lobby_data["chat_id"],
        message_id=lobby_id,
        reply_markup=new_keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@party_router.callback_query(F.data.startswith("party_select_role:"))
async def handle_join_role_selection(callback: CallbackQuery, bot: Bot):
    lobby_id_str = callback.data.split(":")[1]
    if lobby_id_str == "initial": return 
    
    lobby_id = int(lobby_id_str)
    selected_role = callback.data.split(":")[-1]
    user = callback.from_user

    if lobby_id not in active_lobbies:
        await callback.answer("Лобі не знайдено.", show_alert=True)
        return

    lobby_data = active_lobbies[lobby_id]

    if lobby_data.get("state") != "joining" or not lobby_data.get("joining_user") or lobby_data["joining_user"]["id"] != user.id:
        await callback.answer("Зараз не твоя черга приєднуватися.", show_alert=True)
        return

    lobby_data["players"][user.id] = {"name": get_user_display_name(user), "role": selected_role}
    lobby_data["state"] = "open" 
    lobby_data["joining_user"] = None
    
    new_text = get_lobby_message_text(lobby_data)
    new_keyboard = create_lobby_keyboard(lobby_id, lobby_data)
    
    await bot.edit_message_text(
        text=new_text,
        chat_id=lobby_data["chat_id"],
        message_id=lobby_id,
        reply_markup=new_keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer(f"Ти приєднався до паті з роллю: {selected_role}!", show_alert=True)

@party_router.callback_query(F.data.startswith("party_leave:"))
async def handle_leave_lobby(callback: CallbackQuery, bot: Bot):
    lobby_id = int(callback.data.split(":")[-1])
    user = callback.from_user
    
    if lobby_id not in active_lobbies:
        await callback.answer("Цього лобі більше не існує.", show_alert=True)
        return

    lobby_data = active_lobbies[lobby_id]
    
    if user.id not in lobby_data["players"]:
        await callback.answer("Ти не є учасником цього паті.", show_alert=True)
        return
        
    if user.id == lobby_data["leader_id"]:
        await callback.answer("Лідер не може покинути паті. Тільки закрити його.", show_alert=True)
        return
        
    removed_player_info = lobby_data["players"].pop(user.id)
    logger.info(f"Гравець {removed_player_info['name']} покинув лобі {lobby_id}")
    
    new_text = get_lobby_message_text(lobby_data)
    new_keyboard = create_lobby_keyboard(lobby_id, lobby_data)
    try:
        await bot.edit_message_text(
            text=new_text,
            chat_id=lobby_data["chat_id"],
            message_id=lobby_id,
            reply_markup=new_keyboard,
            parse_mode=ParseMode.HTML
        )
        await callback.answer("Ти покинув паті.", show_alert=True)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося оновити повідомлення лобі {lobby_id} після виходу гравця: {e}")
        lobby_data["players"][user.id] = removed_player_info

@party_router.callback_query(F.data.startswith("party_cancel_lobby:"))
async def handle_cancel_lobby(callback: CallbackQuery, bot: Bot):
    lobby_id = int(callback.data.split(":")[-1])
    user = callback.from_user

    if lobby_id not in active_lobbies:
        await callback.answer("Цього лобі більше не існує.", show_alert=True)
        return

    lobby_data = active_lobbies[lobby_id]
    
    if user.id != lobby_data["leader_id"]:
        await callback.answer("Тільки лідер паті може закрити лобі.", show_alert=True)
        return
        
    del active_lobbies[lobby_id]
    logger.info(f"Лобі {lobby_id} скасовано лідером {get_user_display_name(user)}")
    
    try:
        await bot.edit_message_text(
            text="🚫 <b>Лобі закрито ініціатором.</b>",
            chat_id=lobby_data["chat_id"],
            message_id=lobby_id,
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
        await callback.answer("Лобі успішно закрито.", show_alert=True)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося оновити повідомлення при скасуванні лобі {lobby_id}: {e}")

@party_router.callback_query(F.data.startswith("party_cancel_join:"))
async def cancel_join_selection(callback: CallbackQuery, bot: Bot):
    lobby_id = int(callback.data.split(":")[1])
    user = callback.from_user

    if lobby_id not in active_lobbies:
        await callback.answer("Лобі не знайдено.", show_alert=True)
        return
        
    lobby_data = active_lobbies[lobby_id]
    
    if (lobby_data["state"] == "joining" and lobby_data["joining_user"]["id"] == user.id) or (lobby_data["leader_id"] == user.id):
        lobby_data["state"] = "open"
        lobby_data["joining_user"] = None
        
        new_text = get_lobby_message_text(lobby_data)
        new_keyboard = create_lobby_keyboard(lobby_id, lobby_data)
        
        await bot.edit_message_text(
            text=new_text,
            chat_id=lobby_data["chat_id"],
            message_id=lobby_id,
            reply_markup=new_keyboard,
            parse_mode=ParseMode.HTML
        )
        await callback.answer("Приєднання скасовано.")
    else:
        await callback.answer("Ти не можеш скасувати цю дію.", show_alert=True)


# === ЗАГАЛЬНІ ОБРОБНИКИ КОМАНД (без змін) ===
@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    if not user: return
    user_name_escaped = get_user_display_name(user)
    logger.info(f"Користувач {user_name_escaped} (ID: {user.id}) запустив бота /start.")
    kyiv_tz = timezone(timedelta(hours=3))
    current_hour = datetime.now(kyiv_tz).hour
    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else "Доброго дня" if 12 <= current_hour < 17 else "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
    emoji = "🌅" if 5 <= current_hour < 12 else "☀️" if 12 <= current_hour < 17 else "🌆" if 17 <= current_hour < 22 else "🌙"
    
    welcome_caption = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}

Ласкаво просимо до <b>GGenius</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.

<b>Що я можу для тебе зробити:</b>
🔸 Знайти найсвіжішу інформацію в Інтернеті!
🔸 Проаналізувати скріншот твого ігрового профілю.
🔸 Відповісти на запитання по грі.
🔸 Автоматично реагувати на зображення в чаті!

👇 Для початку роботи, використай одну з команд в меню або напиши її:
• <code>/search &lt;твій запит&gt;</code>
• <code>/go &lt;твоє питання&gt;</code>
• <code>/profile</code>
• Або просто надішли будь-яке зображення! 📸
"""
    try:
        await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=welcome_caption, parse_mode=ParseMode.HTML)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото-привітання: {e}. Відправляю текст.")
        await message.answer(welcome_caption, parse_mode=ParseMode.HTML)

@general_router.message(Command("help"))
async def cmd_help(message: Message):
    """Обробник команди /help."""
    help_text = """
ℹ️ <b>Довідка по боту GGenius</b>

Я - ваш AI-помічник для Mobile Legends. Ось список моїх основних команд:

/start - Перезапустити бота та показати вітальне повідомлення.
/profile - Зареєструвати або оновити свій ігровий профіль.
/go <code>&lt;питання&gt;</code> - Задати будь-яке питання про гру (герої, предмети, тактики).
/search <code>&lt;запит&gt;</code> - Знайти останні новини або інформацію в Інтернеті.
/research <code>&lt;запит&gt;</code> - Провести глибокий аналіз теми.
/analyzeprofile - Запустити аналіз скріншота вашого профілю.
/analyzestats - Запустити аналіз скріншота вашої статистики.
/help - Показати це повідомлення.

Також я можу автоматично реагувати на зображення в чаті та підтримувати розмову, якщо ви звернетесь до мене.
"""
    await message.reply(help_text, parse_mode=ParseMode.HTML)

# 🚀 ОНОВЛЕНИЙ ОБРОБНИК /SEARCH
@general_router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    if not user: return
    user_name_escaped = get_user_display_name(user)
    user_id = user.id
    user_query = message.text.replace("/search", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив пошуковий запит: '{user_query}'")

    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 🔎\nНапиши запит після <code>/search</code>, наприклад:\n<code>/search останні зміни балансу героїв</code>", parse_mode=ParseMode.HTML)
        return

    thinking_msg = await message.reply(f"🛰️ {user_name_escaped}, шукаю найсвіжішу інформацію в Інтернеті...")
    start_time = time.time()
    
    async with gpt_client as gpt:
        response_text = await gpt.get_web_search_response(user_name_escaped, user_query)
    
    processing_time = time.time() - start_time
    logger.info(f"Час обробки /search для '{user_query}': {processing_time:.2f}с")

    if not response_text:
        response_text = f"Вибач, {user_name_escaped}, не вдалося отримати відповідь. Спробуй пізніше."

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | OpenAI ({gpt_client.SEARCH_MODEL})</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(
            bot_instance=bot,
            chat_id=message.chat.id,
            text=full_response_to_send,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /search для {user_name_escaped}: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді."
            if thinking_msg: await thinking_msg.edit_text(final_error_msg, parse_mode=None)
            else: await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err:
             logger.error(f"Не вдалося надіслати навіть фінальне повідомлення про помилку: {final_err}")

@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    if not user: return
    user_name_escaped = get_user_display_name(user)
    user_id = user.id
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив запит /go: '{user_query}'")

    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНапиши питання після <code>/go</code>, наприклад:\n<code>/go найкращі герої для міду</code>", parse_mode=ParseMode.HTML)
        return

    thinking_msg = await message.reply(random.choice([f"🤔 Аналізую запит...", f"🧠 Обробляю інформацію...", f"⏳ Хвилинку, шукаю відповідь..."]))
    start_time = time.time()

    response_text = f"Вибач, {user_name_escaped}, сталася помилка генерації відповіді. 😔"
    try:
        async with gpt_client as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}': {e}")

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}': {processing_time:.2f}с")

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | GPT ({gpt_client.TEXT_MODEL})</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(bot, message.chat.id, full_response_to_send, ParseMode.HTML, thinking_msg)
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /go: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді."
            if thinking_msg: await thinking_msg.edit_text(final_error_msg, parse_mode=None)
            else: await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err:
             logger.error(f"Не вдалося надіслати навіть фінальне повідомлення про помилку: {final_err}")

# === НОВИЙ ОБРОБНИК ДЛЯ DEEP RESEARCH ===
@general_router.message(Command("research"))
async def cmd_research(message: Message, bot: Bot):
    """Обробник команди /research для швидкого глибокого аналізу."""
    if not message.from_user:
        return
        
    query = message.text.replace("/research", "").strip()
    user_name = get_user_display_name(message.from_user)

    if not query:
        await message.reply(
            f"Привіт, {user_name}! 🔬\n"
            "Напиши тему для дослідження після <code>/research</code>, наприклад:\n"
            "<code>/research найкращі предмети для стрільців у поточному патчі</code>",
            parse_mode=ParseMode.HTML
        )
        return

    thinking_msg = await message.reply(f"🔬 {user_name}, починаю швидке дослідження... Це може зайняти до хвилини.")
    
    researcher = MLBBDeepResearch(model="o4-mini-deep-research")
    
    try:
        start_time = time.time()
        result = await researcher.start_research_task(query)
        processing_time = time.time() - start_time
        
        output_text = result.get("output_text", "Не вдалося отримати результат.")
        
        admin_info = ""
        if message.from_user.id == ADMIN_USER_ID:
            admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | {researcher.model}</i>"
        
        full_response_to_send = f"{output_text}{admin_info}"
        
        await send_message_in_chunks(bot, message.chat.id, full_response_to_send, ParseMode.HTML, thinking_msg)
    
    except RateLimitError: # 👈 Обробка помилки лімітів
        logger.warning(f"Rate limit exceeded for /research command by user {user_name}")
        await thinking_msg.edit_text(
            f"⏳ {user_name}, зараз забагато запитів до AI-аналітика. "
            "Будь ласка, спробуй ще раз за хвилину."
        )
    except Exception as e:
        logger.error(f"Error during /research command for query '{query}': {e}", exc_info=True)
        await thinking_msg.edit_text(f"Вибач, {user_name}, сталася помилка під час дослідження.")


# === ОБРОБНИКИ ПОВІДОМЛЕНЬ (ФОТО ТА ТЕКСТ) ===
@general_router.message(F.photo)
async def handle_image_messages(message: Message, bot: Bot):
    if not VISION_AUTO_RESPONSE_ENABLED or not message.photo or not message.from_user:
        return

    chat_id = message.chat.id
    current_time = time.time()
    current_user_name = get_user_display_name(message.from_user)
    
    bot_info = await bot.get_me()
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    
    # 🔑 Зберігаємо caption для подальшого використання
    user_caption = message.caption or ""
    
    is_caption_mention = False
    if user_caption:
        is_caption_mention = (f"@{bot_info.username.lower()}" in user_caption.lower() or 
                            any(re.search(r'\b' + name + r'\b', user_caption.lower()) for name in BOT_NAMES))

    should_respond = False
    if is_reply_to_bot or is_caption_mention:
        should_respond = True
    else:
        last_vision_time = vision_cooldowns.get(chat_id, 0)
        if (current_time - last_vision_time) > VISION_RESPONSE_COOLDOWN_SECONDS and random.random() < 0.7:
            should_respond = True
            vision_cooldowns[chat_id] = current_time

    if not should_respond:
        return

    largest_photo: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
    if largest_photo.file_size and largest_photo.file_size > VISION_MAX_IMAGE_SIZE_MB * 1024 * 1024:
        await message.reply(f"Вибач, {current_user_name}, зображення завелике.")
        return

    thinking_msg = None
    try:
        if is_reply_to_bot or is_caption_mention:
            thinking_msg = await message.reply(f"🔍 {current_user_name}, аналізую зображення...")

        file_info = await bot.get_file(largest_photo.file_id)
        if not file_info or not file_info.file_path: return

        image_bytes_io = await bot.download_file(file_info.file_path)
        if not image_bytes_io: return

        image_base64 = base64.b64encode(image_bytes_io.read()).decode('utf-8')
        
        async with gpt_client as gpt:
            # 🔑 Передаємо і зображення, і caption
            vision_response = await gpt.analyze_image_universal(
                image_base64, 
                current_user_name,
                caption_text=user_caption  # Новий параметр
            )

        if vision_response and vision_response.strip():
            content_type = "general"
            response_lower = vision_response.lower()
            if any(word in response_lower for word in ["мем", "смішн", "жарт"]): content_type = "meme"
            elif any(word in response_lower for word in ["скріншот", "гра", "профіль"]): content_type = "screenshot"
            elif any(word in response_lower for word in ["текст", "напис"]): content_type = "text"
            
            emoji = VISION_CONTENT_EMOJIS.get(content_type, "🔍")
            final_response = f"{emoji} {vision_response}" if not any(char in vision_response[:3] for char in VISION_CONTENT_EMOJIS.values()) else vision_response

            if thinking_msg:
                await thinking_msg.edit_text(final_response, parse_mode=None)
            else:
                await message.reply(final_response, parse_mode=None)
            
        elif thinking_msg:
            await thinking_msg.edit_text(f"Хм, {current_user_name}, не можу розібрати, що тут 🤔")
    except Exception as e:
        logger.exception(f"Помилка обробки зображення від {current_user_name}: {e}")
        if thinking_msg: await thinking_msg.delete()
        await message.reply(f"Упс, {current_user_name}, щось пішло не так з обробкою зображення 😅")

@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    if not message.text or message.text.startswith('/') or not message.from_user:
        return

    # Перевірка на наявність посилань у повідомленні
    url_pattern = re.compile(r'https?://\S+')
    if url_pattern.search(message.text):
        logger.info(f"Повідомлення від {message.from_user.id} містить посилання і буде проігноровано.")
        return # Просто ігноруємо повідомлення з посиланнями

    text_lower = message.text.lower()
    chat_id = message.chat.id
    user_id = message.from_user.id
    current_user_name = get_user_display_name(message.from_user)
    current_time = time.time()
    bot_info = await bot.get_me()

    is_explicit_mention = f"@{bot_info.username.lower()}" in text_lower
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_name_mention = any(re.search(r'\b' + name + r'\b', text_lower) for name in BOT_NAMES)

    matched_trigger_mood = next((mood for trigger, mood in CONVERSATIONAL_TRIGGERS.items() if re.search(r'\b' + re.escape(trigger) + r'\b', text_lower)), None)
    if is_reply_to_bot and not matched_trigger_mood:
        matched_trigger_mood = "Користувач відповів на твоє повідомлення. Підтримай розмову."
    if not matched_trigger_mood: return

    should_respond = False
    if is_explicit_mention or is_reply_to_bot or is_name_mention:
        should_respond = True
    elif (current_time - chat_cooldowns.get(chat_id, 0)) > CONVERSATIONAL_COOLDOWN_SECONDS:
        should_respond = True
        chat_cooldowns[chat_id] = current_time

    if should_respond:
        is_personalization_request = any(trigger in text_lower for trigger in PERSONALIZATION_TRIGGERS)
        
        db_user_data = await get_user_by_telegram_id(user_id)
        is_registered = bool(db_user_data)

        if not is_registered and is_personalization_request:
            logger.info(f"Незареєстрований користувач {current_user_name} спробував отримати персоналізовану відповідь.")
            await message.reply(
                f"Привіт, {current_user_name}! 👋\n\n"
                "Бачу, ти хочеш отримати персональну інформацію. Для цього мені потрібно знати твій профіль.\n\n"
                f"Будь ласка, пройди швидку реєстрацію за допомогою команди /profile. Це дозволить мені зберігати твою історію та надавати більш точні відповіді!"
            )
            return

        full_profile_for_prompt = None
        if is_registered:
            user_cache = await load_user_cache(user_id)
            # ✅ FIX: Ensure chat_history is always a list
            chat_history = user_cache.get('chat_history') if user_cache.get('chat_history') is not None else []
            
            # --- 🚀 НОВА ЛОГІКА ЗБАГАЧЕННЯ КОНТЕКСТУ 🚀 ---
            # Завжди готуємо профіль, якщо він є, а не тільки за тригером
            full_profile_for_prompt = user_cache.copy() # Копіюємо, щоб не змінювати кеш
            
            # 1. Витягуємо улюблених героїв у зручний список
            favorite_heroes = []
            for i in range(1, 4):
                hero_name = user_cache.get(f'hero{i}_name')
                if hero_name:
                    favorite_heroes.append(hero_name)
            if favorite_heroes:
                full_profile_for_prompt['favorite_heroes_list'] = favorite_heroes
            
            # 2. Визначаємо рівень гри на основі рангу
            current_rank = user_cache.get('current_rank', '').lower()
            if 'міфіч' in current_rank:
                full_profile_for_prompt['skill_level'] = 'high'
            elif 'легенд' in current_rank or 'епік' in current_rank:
                full_profile_for_prompt['skill_level'] = 'medium'
            else:
                full_profile_for_prompt['skill_level'] = 'developing'
            logger.info(f"Збагачено контекст для {current_user_name}: рівень '{full_profile_for_prompt.get('skill_level', 'N/A')}', герої: {full_profile_for_prompt.get('favorite_heroes_list', [])}")
            # --- 🚀 КІНЕЦЬ НОВОЇ ЛОГІКИ 🚀 ---

        else: # Незареєстрований користувач
            session = await load_session(user_id)
            chat_history = session.chat_history
            full_profile_for_prompt = None

        chat_history.append({"role": "user", "content": message.text})
        if len(chat_history) > MAX_CHAT_HISTORY_LENGTH:
            chat_history = chat_history[-MAX_CHAT_HISTORY_LENGTH:]

        try:
            async with gpt_client as gpt:
                reply_text = await gpt.generate_conversational_reply(
                    user_name=current_user_name,
                    chat_history=chat_history,
                    trigger_mood=matched_trigger_mood,
                    user_profile_data=full_profile_for_prompt # Передаємо збагачений профіль
                )
            
            if reply_text and "<i>" not in reply_text:
                chat_history.append({"role": "assistant", "content": reply_text})
                
                if is_registered and 'user_cache' in locals():
                    user_cache['chat_history'] = chat_history
                    await save_user_cache(user_id, user_cache)
                else:
                    session.chat_history = chat_history
                    await save_session(user_id, session)

                await message.reply(reply_text)
        except Exception as e:
            logger.exception(f"Помилка генерації адаптивної відповіді: {e}")


# === ГЛОБАЛЬНИЙ ОБРОБНИК ПОМИЛОК (без змін) ===
async def error_handler(event: types.ErrorEvent, bot: Bot):
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=event.exception)
    chat_id, user_name = None, "друже"
    update = event.update
    if update.message:
        chat_id = update.message.chat.id
        user_name = get_user_display_name(update.message.from_user)
    elif update.callback_query and update.callback_query.message:
        chat_id = update.callback_query.message.chat.id
        user_name = get_user_display_name(update.callback_query.from_user)
        try: await update.callback_query.answer("Сталася помилка...", show_alert=False)
        except TelegramAPIError: pass
    
    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔"
    if "TelegramAPIError" in str(event.exception):
        error_message_text = f"Упс, {user_name}, проблема з Telegram API 📡 Спробуй ще раз."
    
    if chat_id:
        try: await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except TelegramAPIError as e: logger.error(f"Не вдалося надіслати повідомлення про помилку в чат {chat_id}: {e}")

# === РЕЄСТРАЦІЯ ОБРОБНИКІВ ===
def register_general_handlers(dp: Dispatcher):
    """Реєструє всі загальні обробники (паті та основні)."""
    dp.include_router(party_router)
    dp.include_router(general_router)
    logger.info("🚀 Обробники для паті, команд, тригерів та Vision успішно зареєстровано.")