"""
Обробники для створення та управління ігровим лобі (паті).

Цей модуль містить повну логіку для:
- Розпізнавання запиту на створення паті в чаті.
- Покрокового створення лобі за допомогою FSM (вибір режиму, розміру, ролей).
- Створення та оновлення інтерактивного повідомлення-лобі.
- Обробки дій гравців: приєднання, вихід, вибір ролі.
- Управління лобі лідером: закриття.
- ❗️ НОВЕ: Інтеграція рангів гравців та сповіщення про повний збір.
"""
import asyncio
import html
import logging
import re
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import CallbackQuery, Message

# ❗️ НОВІ ІМПОРТИ
from database.crud import get_user_settings, get_user_by_telegram_id
from keyboards.inline_keyboards import (
    ALL_ROLES,
    create_game_mode_keyboard,
    create_lobby_keyboard,
    create_party_confirmation_keyboard,
    create_party_info_keyboard,
    create_party_size_keyboard,
    create_required_roles_keyboard,
    create_role_selection_keyboard,
)

logger = logging.getLogger(__name__)

# === ІНІЦІАЛІЗАЦІЯ РОУТЕРА ТА СХОВИЩА ===
party_router = Router()
active_lobbies: dict[int, dict] = {}


# === СТАНИ FSM ДЛЯ СТВОРЕННЯ ПАТІ ===
class PartyCreationFSM(StatesGroup):
    """Розширені стани для покрокового процесу створення паті."""
    waiting_for_confirmation = State()
    waiting_for_game_mode = State()
    waiting_for_party_size = State()
    waiting_for_role_selection = State()
    waiting_for_required_roles = State()


# === ДОПОМІЖНІ ФУНКЦІЇ ===

def get_user_display_name(user: Message | CallbackQuery) -> str:
    """Отримує найкраще ім'я для відображення з об'єкта User."""
    from_user = user.from_user
    if not from_user:
        return "друже"
    if from_user.first_name and from_user.first_name.strip():
        return html.escape(from_user.first_name.strip())
    if from_user.username and from_user.username.strip():
        return html.escape(from_user.username.strip())
    return "друже"

async def _get_user_rank(user_id: int) -> str:
    """Отримує ранг користувача з БД, якщо він зареєстрований."""
    user_data = await get_user_by_telegram_id(user_id)
    if user_data and user_data.get("current_rank"):
        return user_data["current_rank"]
    return "невідомий"


def is_party_request_message(message: Message) -> bool:
    """Перевіряє, чи є повідомлення запитом на створення паті."""
    if not message.text:
        return False
    try:
        text_lower = message.text.lower()
        has_party_keywords = re.search(r'\b(паті|пати|команду)\b', text_lower) is not None
        has_action_keywords = re.search(r'\b(збир|го|шука|грат|зібра)\w*\b|\+', text_lower) is not None
        return has_party_keywords and has_action_keywords
    except (AttributeError, TypeError):
        return False

def get_lobby_message_text(lobby_data: dict, joining_user_name: str | None = None) -> str:
    """Створює розширений та візуально привабливий текст для лобі-повідомлення."""
    leader_name = html.escape(lobby_data['leader_name'])
    game_mode = lobby_data.get('game_mode', 'Ranked')
    party_size = lobby_data.get('party_size', 5)

    game_mode_map = {"Ranked": "🏆 Рейтинг", "Classic": "🕹️ Класика", "Brawl": "⚔️ Режим бою"}
    mode_display = game_mode_map.get(game_mode, game_mode)

    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}

    sorted_players = sorted(lobby_data['players'].items(), key=lambda item: ALL_ROLES.index(item[1]['role']))
    
    # ❗️ ОНОВЛЕНО: Додаємо ранг до відображення гравця
    players_list = []
    for _, player_info in sorted_players:
        player_name = html.escape(player_info['name'])
        player_role = player_info['role']
        player_rank = html.escape(player_info.get('rank', 'невідомий'))
        players_list.append(
            f"  {role_emoji_map.get(player_role, '🔹')} <b>{player_role}:</b> {player_name} (<i>{player_rank}</i>)"
        )
    
    taken_roles = [player_info['role'] for _, player_info in sorted_players]
    available_slots_count = party_size - len(players_list)
    progress_bar = "🟢" * len(players_list) + "⚪" * available_slots_count

    text_parts = [
        f"<b>{mode_display}</b>",
        f"<b>🧑‍🤝‍🧑 ЗБІР КОМАНДИ</b>",
        "─────────────────",
        f"👑 <b>Лідер:</b> {leader_name}",
        f"📊 <b>Прогрес:</b> {progress_bar} ({len(players_list)}/{party_size})",
    ]

    if players_list:
        text_parts.append("\n👥 <b>СКЛАД КОМАНДИ:</b>")
        text_parts.extend(players_list)

    if lobby_data.get('state') == 'joining' and joining_user_name:
        text_parts.append(f"\n⏳ <b>{html.escape(joining_user_name)}, оберіть свою роль...</b>")
    elif available_slots_count > 0:
        required_roles = lobby_data.get('required_roles', [])
        available_roles = [r for r in (required_roles or ALL_ROLES) if r not in taken_roles]
        
        section_title = "🔍 <b>ШУКАЄМО</b>" if required_roles else "🆓 <b>ДОСТУПНО</b>"
        if available_roles:
            text_parts.append(f"\n{section_title}:")
            text_parts.extend([f"  {role_emoji_map.get(r, '🔹')} {r}" for r in available_roles])
        
        text_parts.append("\n💬 <i>Натисни кнопку, щоб приєднатися!</i>")
    else:
        # Цей блок більше не використовується, оскільки є функція notify_and_close_full_lobby
        text_parts.append("\n\n✅ <b>КОМАНДА ГОТОВА! ПОГНАЛИ! 🚀</b>")
        
    return f"<blockquote>" + "\n".join(text_parts) + "</blockquote>"


# === ❗️ ОНОВЛЕНА ФУНКЦІЯ СПОВІЩЕННЯ ===
async def notify_and_close_full_lobby(bot: Bot, lobby_id: int, lobby_data: dict[str, Any]):
    """
    Сповіщає учасників про повний збір, закриває лобі та видаляє його з активних.
    """
    logger.info(f"Команда для лобі {lobby_id} повністю зібрана. Розсилаю сповіщення.")
    
    chat_id = lobby_data["chat_id"]
    chat_title = lobby_data.get("chat_title", "цьому чаті")
    chat_username = lobby_data.get("chat_username")
    players = lobby_data.get("players", {})
    
    role_emoji_map = {"EXP": "⚔️", "ЛІС": "🌳", "МІД": "🧙", "АДК": "🏹", "РОУМ": "🛡️"}
    
    # Сортуємо гравців за роллю для красивого виводу
    sorted_players = sorted(players.items(), key=lambda item: ALL_ROLES.index(item[1]['role']))
    
    # Формуємо список учасників з ролями
    participants_list = []
    for player_id, player_info in sorted_players:
        mention = f"<a href='tg://user?id={player_id}'>{html.escape(player_info['name'])}</a>"
        role = player_info['role']
        rank = html.escape(player_info.get('rank', 'невідомий'))
        emoji = role_emoji_map.get(role, '🔹')
        participants_list.append(
            f"  {emoji} <b>{role}:</b> {mention} (<i>{rank}</i>)"
        )
    
    # Формуємо повідомлення для групового чату
    group_message_parts = [
        "✅ <b>КОМАНДА ГОТОВА!</b>",
        "",
        "Склад зібрано, погнали підкорювати ранги! 🚀",
        "",
        "👥 <b>УЧАСНИКИ:</b>",
        *participants_list,
        "",
        "<i>P.S. Лідер, не забудь додати всіх у друзі та створити ігрове лобі.</i>"
    ]
    group_message_text = "<blockquote>" + "\n".join(group_message_parts) + "</blockquote>"

    try:
        await bot.edit_message_text(
            text=group_message_text,
            chat_id=chat_id,
            message_id=lobby_id,
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        logger.error(f"Не вдалося оновити фінальне повідомлення для лобі {lobby_id}: {e}")

    # Формуємо посилання на чат
    if chat_username:
        chat_link = f"https://t.me/{chat_username}"
    else:
        # Для приватних чатів посилання на повідомлення є більш надійним
        # Використовуємо -100 префікс для ID супергруп
        supergroup_chat_id = str(chat_id).replace("-100", "")
        chat_link = f"https://t.me/c/{supergroup_chat_id}/{lobby_id}"

    # Формуємо особисте повідомлення
    dm_parts = [
        f"🔥 <b>Паті в чаті «<a href='{chat_link}'>{html.escape(chat_title)}</a>» повністю зібрано!</b>",
        "",
        "👥 <b>ВАША КОМАНДА:</b>",
        *participants_list,
        "",
        f"🔗 <b><a href='{chat_link}'>Повернутися в чат</a></b>, щоб зв'язатися з командою.",
        "Успішної гри! ⭐"
    ]
    dm_text = "\n".join(dm_parts)

    # Розсилка особистих повідомлень
    for player_id in players.keys():
        try:
            await bot.send_message(player_id, dm_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            await asyncio.sleep(0.1) # Невеликий таймаут, щоб уникнути спам-фільтрів
        except TelegramAPIError as e:
            logger.warning(f"Не вдалося надіслати особисте повідомлення гравцю {player_id} з лобі {lobby_id}: {e}")
            
    # Видаляємо лобі з активних
    if lobby_id in active_lobbies:
        del active_lobbies[lobby_id]
        logger.info(f"Лобі {lobby_id} успішно закрито та видалено з пам'яті.")


# === ЛОГІКА СТВОРЕННЯ ПАТІ (FSM) ===

@party_router.message(F.text & F.func(is_party_request_message))
async def ask_for_party_creation(message: Message, state: FSMContext):
    """Обробник, що реагує на запит створення паті, з перевіркою м'юту."""
    if not message.from_user:
        return
        
    user_id = message.from_user.id
    user_name = get_user_display_name(message)
    
    settings = await get_user_settings(user_id)
    if settings.mute_party:
        logger.info(f"Ігнорую запит на паті від {user_name} (ID: {user_id}), оскільки mute_party=True.")
        return

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
        "1. Я покроково запитаю тебе про режим гри, кількість гравців та бажані ролі.\n"
        "2. Я створю лобі-повідомлення, до якого зможуть приєднатися інші гравці.\n"
        "3. Учасники зможуть обрати вільну роль, а ти, як лідер, зможеш закрити лобі.\n\n"
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
    chat = callback.message.chat
    state_data = await state.get_data()
    
    user_name = get_user_display_name(callback)
    # ❗️ Отримуємо ранг лідера
    user_rank = await _get_user_rank(user.id)
    lobby_id = callback.message.message_id
    
    leader_role = state_data.get("leader_role")
    required_roles = state_data.get("selected_required_roles", [])
    
    lobby_data = {
        "leader_id": user.id,
        "leader_name": user_name,
        "players": {user.id: {"name": user_name, "role": leader_role, "rank": user_rank}},
        "chat_id": chat.id,
        "chat_title": chat.title,
        "chat_username": chat.username,
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


# === ОБРОБНИКИ ДЛЯ КНОПОК "НАЗАД" ===

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


# === ЛОГІКА ВЗАЄМОДІЇ З ЛОБІ ===

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
    user_name = get_user_display_name(callback)
    lobby_data["joining_user"] = {"id": user.id, "name": user_name}
    
    new_text = get_lobby_message_text(lobby_data, joining_user_name=user_name)
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
    parts = callback.data.split(":")
    if parts[1] == "initial": return 
    
    lobby_id = int(parts[1])
    selected_role = parts[-1]
    user = callback.from_user

    if lobby_id not in active_lobbies:
        await callback.answer("Лобі не знайдено.", show_alert=True)
        return

    lobby_data = active_lobbies[lobby_id]

    if lobby_data.get("state") != "joining" or not lobby_data.get("joining_user") or lobby_data["joining_user"]["id"] != user.id:
        await callback.answer("Зараз не твоя черга приєднуватися.", show_alert=True)
        return

    user_name = get_user_display_name(callback)
    # ❗️ Отримуємо ранг гравця, що приєднався
    user_rank = await _get_user_rank(user.id)
    lobby_data["players"][user.id] = {"name": user_name, "role": selected_role, "rank": user_rank}
    lobby_data["state"] = "open" 
    lobby_data["joining_user"] = None
    
    # ❗️ Перевіряємо, чи заповнилося лобі
    if len(lobby_data["players"]) >= lobby_data.get("party_size", 5):
        await notify_and_close_full_lobby(bot, lobby_id, lobby_data)
        await callback.answer(f"Ти приєднався до паті! Команда зібрана!", show_alert=True)
    else:
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
    user_name = get_user_display_name(callback)

    if lobby_id not in active_lobbies:
        await callback.answer("Цього лобі більше не існує.", show_alert=True)
        return

    lobby_data = active_lobbies[lobby_id]
    
    if user.id != lobby_data["leader_id"]:
        await callback.answer("Тільки лідер паті може закрити лобі.", show_alert=True)
        return
        
    del active_lobbies[lobby_id]
    logger.info(f"Лобі {lobby_id} скасовано лідером {user_name}")
    
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


# === РЕЄСТРАЦІЯ ОБРОБНИКІВ ===
def register_party_handlers(dp: Router):
    """Реєструє всі обробники для функціоналу паті."""
    dp.include_router(party_router)
    logger.info("✅ Обробники для створення та управління паті успішно зареєстровано.")