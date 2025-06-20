"""
Головний модуль обробки взаємодій з користувачем.

Цей модуль реалізує архітектуру "пріоритетних обробників", яка поєднує
надійність конкретних функцій (створення паті) з харизмою та гнучкістю
інтелектуального AI-співрозмовника.
"""
import html
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

import database
from config import (
    logger, PARTY_TRIGGER_PHRASES, PARTY_LOBBY_ROLES, OPENAI_API_KEY, WELCOME_IMAGE_URL,
    ADMIN_USER_ID, MAX_CHAT_HISTORY_LENGTH, BOT_NAMES,
    CONVERSATIONAL_COOLDOWN_SECONDS
)
# === ВИРІШЕННЯ ПРОБЛЕМИ: ImportError ===
# Ми замінюємо неіснуючий імпорт 'create_party_lobby_keyboard' на правильну,
# актуальну назву 'create_dynamic_lobby_keyboard', як того вимагає
# оновлена версія файлу з клавіатурами.
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard,
    create_dynamic_lobby_keyboard,  # Виправлений імпорт
    create_party_size_keyboard,
    create_role_selection_keyboard,
    create_lobby_lifetime_keyboard
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks

general_router = Router()

# FSM стани для обох функціональностей
class ConversationalFSM(StatesGroup):
    """Стан для ведення безперервного діалогу з користувачем."""
    chatting = State()

class PartyFSM(StatesGroup):
    """Стани для процесу створення ігрового лобі."""
    waiting_for_size = State()
    waiting_for_lifetime = State()
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()

conversational_cooldown_cache: Dict[int, float] = defaultdict(float)

# === ФІЛЬТРИ ТА ДОПОМІЖНІ ФУНКЦІЇ ===

async def is_bot_mentioned_or_private(message: types.Message, bot_info: types.User) -> bool:
    """Перевіряє, чи звертаються до бота (в приваті, через reply або згадку)."""
    if message.chat.type == 'private': return True
    if message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id: return True
    if message.text:
        bot_username = f"@{bot_info.username}"
        return bot_username.lower() in message.text.lower() or any(
            name.lower() in message.text.lower() for name in BOT_NAMES
        )
    return False

def contains_party_phrase(text: str) -> bool:
    """Перевіряє, чи містить текст тригерні фрази для пошуку паті."""
    if not text: return False
    return any(phrase.lower() in text.lower() for phrase in PARTY_TRIGGER_PHRASES)

async def format_lobby_message(lobby_data: Dict[str, Any]) -> str:
    """Форматує текстове представлення ігрового лобі."""
    players = lobby_data.get("players", {})
    party_size = lobby_data.get("party_size", 5)
    player_lines = [f"✅ <b>{html.escape(p['full_name'])}</b> — <i>{p['role']}</i>" for p in players.values()]
    players_text = "\n".join(player_lines) if player_lines else "<i>Поки що нікого...</i>"
    roles_text = "\n".join([f"• {role}" for role in lobby_data["roles_left"]]) if lobby_data["roles_left"] else "<i>Всі ролі зайняті!</i>"
    expires_dt = datetime.fromtimestamp(lobby_data['expires_at'], tz=timezone(timedelta(hours=3)))
    expires_str = expires_dt.strftime('%H:%M, %d.%m')
    return (f"🔥 <b>Збираємо паті! (до {expires_str})</b>\n\n"
            f"<b>Гравці в паті ({len(players)}/{party_size}):</b>\n{players_text}\n\n"
            f"<b>Вільні ролі:</b>\n{roles_text}")

async def update_lobby_message(bot: Bot, chat_id: int, user_id: int | None = None) -> None:
    """Оновлює існуюче повідомлення лобі з актуальними даними."""
    lobby_data = database.get_lobby(chat_id)
    if not lobby_data: return
    try:
        new_text = await format_lobby_message(lobby_data)
        keyboard_user_id = user_id if user_id is not None else 0
        # === ВИРІШЕННЯ ПРОБЛЕМИ: Використання правильної функції ===
        # Тут ми також замінюємо виклик старої функції на нову 'create_dynamic_lobby_keyboard'.
        await bot.edit_message_text(
            text=new_text, chat_id=chat_id, message_id=lobby_data["message_id"],
            reply_markup=create_dynamic_lobby_keyboard(keyboard_user_id, lobby_data),
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        if "message to edit not found" in str(e) or "message is not modified" in str(e):
            logger.warning(f"[Party] Спроба оновити неіснуюче повідомлення лобі в чаті {chat_id}.")
        else:
            logger.error(f"[Party] Не вдалося оновити повідомлення лобі: {e}")

# === АРХІТЕКТУРА ПРІОРИТЕТНИХ ОБРОБНИКІВ ===

# ПРІОРИТЕТ №1: СТВОРЕННЯ ПАТІ
@general_router.message(
    F.text,
    lambda message: contains_party_phrase(message.text)
)
async def on_party_trigger(message: types.Message, state: FSMContext) -> None:
    """Обробник з найвищим пріоритетом. Реагує на ключові фрази для створення паті."""
    logger.info(f"[Party] Спрацював тригер створення паті для {message.from_user.id}.")
    if database.get_lobby(message.chat.id):
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь!")
        return
    await message.reply(
        "Бачу, ти хочеш зібрати паті. Допомогти тобі створити лобі?",
        reply_markup=create_party_confirmation_keyboard()
    )
    await state.clear()

# ПРІОРИТЕТ №2: ПРЯМІ КОМАНДИ
@general_router.message(Command("go"))
async def cmd_go(message: types.Message, bot: Bot) -> None:
    """Обробляє явну команду /go для постановки питання."""
    user_name = html.escape(message.from_user.first_name)
    query = message.text.replace("/go", "", 1).strip()
    if not query:
        await message.reply("Будь ласка, напишіть ваше питання після команди /go.")
        return
    thinking_msg = await message.reply("⏳ Аналізую ваше питання...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response = await gpt.get_response(user_name, query)
        await send_message_in_chunks(
            bot, chat_id=message.chat.id, text=response,
            parse_mode=ParseMode.HTML, initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Помилка в обробнику cmd_go: {e}", exc_info=True)
        await thinking_msg.edit_text("На жаль, сталася помилка під час обробки вашого запиту. 😔")

# ПРІОРИТЕТ №3: ІНТЕЛЕКТУАЛЬНЕ СПІЛКУВАННЯ
@general_router.message(
    is_bot_mentioned_or_private,
    F.text,
    lambda message: not contains_party_phrase(message.text)
)
async def on_bot_interaction(message: types.Message, state: FSMContext, bot: Bot) -> None:
    """"Мозок" бота для вільного спілкування."""
    user_id = message.from_user.id
    current_time = time.time()
    if current_time - conversational_cooldown_cache[user_id] < CONVERSATIONAL_COOLDOWN_SECONDS:
        logger.info(f"[General] Кулдаун для {user_id}. Повідомлення проігноровано.")
        return
    await state.set_state(ConversationalFSM.chatting)
    user_data = await state.get_data()
    history = user_data.get('history', [])
    history.append({"role": "user", "content": message.text})
    if len(history) > MAX_CHAT_HISTORY_LENGTH:
        history = history[-MAX_CHAT_HISTORY_LENGTH:]
    thinking_msg = await message.reply("🤔...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response_with_history(
                history=history, user_name=message.from_user.full_name
            )
        history.append({"role": "assistant", "content": response_text})
        await state.update_data(history=history)
        await send_message_in_chunks(
            bot, chat_id=message.chat.id, text=response_text,
            parse_mode=ParseMode.HTML, initial_message_to_edit=thinking_msg
        )
        conversational_cooldown_cache[user_id] = current_time
    except Exception as e:
        logger.error(f"Помилка в on_bot_interaction: {e}", exc_info=True)
        await thinking_msg.edit_text("Ой, щось пішло не так. Спробуйте ще раз.")
        await state.clear()

@general_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    """Обробляє команду /start, вітаючи користувача."""
    await state.clear()
    user_name = html.escape(message.from_user.first_name)
    welcome_text = (
        f"Привіт, <b>{user_name}</b>! Я твій AI-помічник для MLBB.\n\n"
        "<b>Що я можу:</b>\n"
        "• Допомогти знайти паті (напиши 'го паті').\n"
        "• Відповісти на питання про гру (/go або згадай мене).\n"
        "• Аналізувати скріншоти профілю та статистики.\n\n"
        "Просто почни спілкування!"
    )
    try:
        await message.answer_photo(WELCOME_IMAGE_URL, caption=welcome_text)
    except TelegramAPIError:
        await message.answer(welcome_text)

async def error_handler(event: types.ErrorEvent, bot: Bot) -> None:
    """Глобальний обробник помилок. Логує винятки та повідомляє користувача."""
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=True)
    chat_id = None
    if event.update.callback_query:
        chat_id = event.update.callback_query.message.chat.id
        try: await event.update.callback_query.answer("Сталася помилка...", show_alert=True)
        except TelegramAPIError: pass
    elif event.update.message:
        chat_id = event.update.message.chat.id
    if chat_id:
        await bot.send_message(chat_id, "😔 Вибачте, сталася непередбачена системна помилка.")

def register_general_handlers(dp: Dispatcher) -> None:
    """Реєструє всі загальні обробники в головному диспетчері."""
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (v5.2 - ImportError Hotfix) успішно зареєстровано.")

# !!! СЮДИ ПОТРІБНО ДОДАТИ РЕШТУ ОБРОБНИКІВ ДЛЯ FSM ПАТІ-МЕНЕДЖЕРА !!!
# (наприклад, @general_router.callback_query(F.data == "party_create_yes"))
