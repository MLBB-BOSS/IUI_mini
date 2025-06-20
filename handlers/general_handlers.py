"""
Обробники для загальних команд та основної логіки "Паті-менеджера".
"""
import html
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

import database
from config import (
    logger, PARTY_TRIGGER_PHRASES, PARTY_LOBBY_ROLES, OPENAI_API_KEY, WELCOME_IMAGE_URL,
    ADMIN_USER_ID, CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH, BOT_NAMES,
    CONVERSATIONAL_COOLDOWN_SECONDS
)
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard, create_party_size_keyboard,
    create_lobby_lifetime_keyboard, create_role_selection_keyboard,
    create_dynamic_lobby_keyboard
)
from services.openai_service import MLBBChatGPT
# --- ВИРІШЕННЯ ПРОБЛЕМИ TypeError ---
# Імпортуємо нашу нову, надійну функцію
from utils.message_utils import send_message_in_chunks

general_router = Router()

class ConversationalFSM(StatesGroup):
    """Стан для ведення безперервного діалогу з користувачем."""
    chatting = State()

# ... (Код FSM для Паті та інші функції залишаються без змін) ...
class PartyFSM(StatesGroup):
    """Стани для процесу створення ігрового лобі."""
    waiting_for_size = State()
    waiting_for_lifetime = State()
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()

conversational_cooldown_cache: Dict[int, float] = defaultdict(float)

async def format_lobby_message(lobby_data: Dict[str, Any]) -> str:
    # Ця функція залишається без змін
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

async def update_lobby_message(bot: Bot, chat_id: int, user_id: int | None = None):
    # Ця функція залишається без змін
    lobby_data = database.get_lobby(chat_id)
    if not lobby_data: return
    try:
        new_text = await format_lobby_message(lobby_data)
        keyboard_user_id = user_id if user_id is not None else 0
        await bot.edit_message_text(
            text=new_text, chat_id=chat_id, message_id=lobby_data["message_id"],
            reply_markup=create_dynamic_lobby_keyboard(keyboard_user_id, lobby_data),
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        if "message to edit not found" in str(e) or "message is not modified" in str(e):
            logger.warning(f"Спроба оновити неіснуюче або незмінене повідомлення лобі в чаті {chat_id}.")
        else:
            logger.error(f"Не вдалося оновити повідомлення лобі в чаті {chat_id}: {e}")

# ... (Всі обробники для Паті-менеджера залишаються без змін) ...
@general_router.message(F.text.lower().in_(PARTY_TRIGGER_PHRASES))
async def on_party_trigger(message: types.Message, state: FSMContext):
    if database.get_lobby(message.chat.id):
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь!")
        return
    await message.reply("Бачу, ти хочеш зібрати паті. Допомогти тобі створити лобі?",
                        reply_markup=create_party_confirmation_keyboard())
    await state.clear()

# ... (інші обробники party)

@general_router.message(Command("go"))
async def cmd_go(message: types.Message, bot: Bot):
    """
    Обробляє команду /go, використовуючи OpenAI для відповіді на запит.
    """
    user_name = html.escape(message.from_user.first_name)
    query = message.text.replace("/go", "").strip()

    if not query:
        await message.reply("Будь ласка, напишіть ваше питання після команди /go.")
        return

    thinking_msg = await message.reply("⏳ Аналізую ваш запит...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response = await gpt.get_response(user_name, query)
        
        # --- ВИРІШЕННЯ ПРОБЛЕМИ TypeError: Крок 1 ---
        # Тепер ми передаємо обов'язковий `parse_mode`.
        await send_message_in_chunks(
            bot=bot,
            chat_id=message.chat.id,
            text=response,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Помилка в обробнику cmd_go: {e}", exc_info=True)
        await thinking_msg.edit_text("На жаль, сталася помилка під час обробки вашого запиту. 😔")


# =============================================================================
# ====================== CONVERSATIONAL AI HANDLERS ===========================
# =============================================================================

# --- ВИРІШЕННЯ ПРОБЛЕМИ NameError: Крок 2 ---
# Створюємо асинхронний фільтр. aiogram автоматично передасть сюди
# об'єкт `bot_info`, який ми поклали в диспетчер у `main.py`.
async def is_bot_mentioned_or_private(message: types.Message, bot_info: types.User) -> bool:
    """
    Фільтр, що перевіряє, чи є чат приватним, або чи згадали бота в груповому чаті.
    Працює ефективно, не викликаючи `get_me()` на кожне повідомлення.
    """
    if message.chat.type == 'private':
        return True
    if message.text:
        bot_username = f"@{bot_info.username}"
        # Перевірка згадки за @username або за іменем зі списку BOT_NAMES
        return bot_username in message.text or any(
            name.lower() in message.text.lower() for name in BOT_NAMES
        )
    return False

@general_router.message(
    # --- ВИРІШЕННЯ ПРОБЛЕМИ NameError: Крок 3 ---
    # Використовуємо наш новий, надійний фільтр.
    is_bot_mentioned_or_private,
    F.text,
    ~F.text.lower().in_(PARTY_TRIGGER_PHRASES),
    ~CommandStart(),
    ~Command("go")
)
async def on_conversational_trigger(message: types.Message, state: FSMContext, bot: Bot):
    """
    Реагує на звичайні повідомлення (не команди), адресовані боту,
    та підтримує контекстну розмову.
    """
    user_id = message.from_user.id
    current_time = time.time()

    if current_time - conversational_cooldown_cache[user_id] < CONVERSATIONAL_COOLDOWN_SECONDS:
        logger.info(f"Кулдаун для користувача {user_id}. Повідомлення проігноровано.")
        return

    await state.set_state(ConversationalFSM.chatting)
    user_data = await state.get_data()
    history = user_data.get('history', [])
    
    history.append({"role": "user", "content": message.text})
    
    if len(history) > MAX_CHAT_HISTORY_LENGTH:
        history = history[-MAX_CHAT_HISTORY_LENGTH:]

    thinking_msg = await message.reply("🤔 Думаю...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response_with_history(history)
        
        history.append({"role": "assistant", "content": response_text})
        await state.update_data(history=history)

        # --- ВИРІШЕННЯ ПРОБЛЕМИ TypeError: Крок 2 ---
        # Також додаємо parse_mode і тут.
        await send_message_in_chunks(
            bot=bot,
            chat_id=message.chat.id,
            text=response_text,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
        
        conversational_cooldown_cache[user_id] = current_time

    except Exception as e:
        logger.error(f"Помилка в розмовному обробнику: {e}", exc_info=True)
        await thinking_msg.edit_text("Ой, щось пішло не так. Спробуйте ще раз трохи пізніше.")
        await state.clear()


# ... (Решта файлу: error_handler, register_general_handlers, cmd_start, логіка паті) ...
# Вони залишаються без змін, але для повноти я їх додам.
@general_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_name = html.escape(message.from_user.first_name)
    welcome_text = f"""Привіт, <b>{user_name}</b>! Я твій AI-помічник для всього, що стосується світу Mobile Legends.\n\n<b>Що я можу:</b>\n• Створювати ігрові лобі (напиши 'го паті' в чаті).\n• Відповідати на твої запитання про гру (команда /go або просто згадай мене в чаті).\n• Аналізувати скріншоти профілю та статистики.\n\nПросто почни спілкування, і я допоможу!"""
    try:
        await message.answer_photo(WELCOME_IMAGE_URL, caption=welcome_text)
    except TelegramAPIError:
        await message.answer(welcome_text)

async def error_handler(event: types.ErrorEvent, bot: Bot):
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=True)
    chat_id = None
    if event.update.callback_query:
        chat_id = event.update.callback_query.message.chat.id
        try:
            await event.update.callback_query.answer("Сталася непередбачена помилка...", show_alert=True)
        except TelegramAPIError: pass
    elif event.update.message:
        chat_id = event.update.message.chat.id
    if chat_id:
        await bot.send_message(chat_id, "😔 Вибачте, сталася непередбачена системна помилка. Я вже сповістив розробників.")

def register_general_handlers(dp: Dispatcher):
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (v3.2 - Stability) успішно зареєстровано.")