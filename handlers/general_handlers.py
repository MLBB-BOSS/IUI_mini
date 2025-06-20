"""
Головний модуль обробки взаємодій з користувачем.

Цей модуль реалізує архітектуру "AI-маршрутизатора". Замість багатьох
конфліктуючих обробників, тут є один головний (`on_bot_interaction`),
який перехоплює всі звернення до бота. Він використовує AI для визначення
наміру користувача (`create_lobby`, `ask_question`, `general_chat`) і,
в залежності від результату, викликає відповідну внутрішню логіку.

Це забезпечує нульовий конфлікт між тригерами та дозволяє боту
розуміти природну мову замість жорстких команд.
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
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard, create_party_size_keyboard,
    create_lobby_lifetime_keyboard, create_role_selection_keyboard,
    create_dynamic_lobby_keyboard
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks

general_router = Router()

# FSM стани залишаються без змін, вони потрібні для покрокових процесів
class ConversationalFSM(StatesGroup):
    chatting = State()

class PartyFSM(StatesGroup):
    waiting_for_size = State()
    waiting_for_lifetime = State()
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()

conversational_cooldown_cache: Dict[int, float] = defaultdict(float)

# =============================================================================
# ======================== ВНУТРІШНЯ ЛОГІКА ДІЙ ===============================
# =============================================================================

async def _start_party_creation(message: types.Message, state: FSMContext):
    """
    Ініціює процес створення паті. Викликається AI-маршрутизатором.
    """
    if database.get_lobby(message.chat.id):
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь!")
        return
    await message.reply(
        "Бачу, ти хочеш зібрати паті. Допомогти тобі створити лобі?",
        reply_markup=create_party_confirmation_keyboard()
    )
    await state.clear()

async def _handle_question(message: types.Message, bot: Bot):
    """
    Обробляє конкретне питання до AI. Викликається AI-маршрутизатором.
    """
    user_name = html.escape(message.from_user.first_name)
    query = message.text
    
    thinking_msg = await message.reply("⏳ Аналізую ваше питання...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response = await gpt.get_response(user_name, query)
        await send_message_in_chunks(
            bot=bot, chat_id=message.chat.id, text=response,
            parse_mode=ParseMode.HTML, initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Помилка в обробнику питань _handle_question: {e}", exc_info=True)
        await thinking_msg.edit_text("На жаль, сталася помилка під час обробки вашого запиту. 😔")

async def _handle_general_chat(message: types.Message, state: FSMContext, bot: Bot):
    """
    Веде загальну розмову. Викликається AI-маршрутизатором.
    """
    await state.set_state(ConversationalFSM.chatting)
    user_data = await state.get_data()
    history = user_data.get('history', [])
    
    history.append({"role": "user", "content": message.text})
    
    if len(history) > MAX_CHAT_HISTORY_LENGTH:
        history = history[-MAX_CHAT_HISTORY_LENGTH:]

    thinking_msg = await message.reply("🤔 Думаю...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.generate_conversational_reply(
                user_name=message.from_user.full_name,
                chat_history=history,
                trigger_mood="Дружня та дотепна відповідь на повідомлення в чаті."
            )
        
        history.append({"role": "assistant", "content": response_text})
        await state.update_data(history=history)

        await send_message_in_chunks(
            bot=bot, chat_id=message.chat.id, text=response_text,
            parse_mode=ParseMode.HTML, initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Помилка в розмовному обробнику _handle_general_chat: {e}", exc_info=True)
        await thinking_msg.edit_text("Ой, щось пішло не так. Спробуйте ще раз трохи пізніше.")
        await state.clear()

# =============================================================================
# ===================== ГОЛОВНИЙ AI-МАРШРУТИЗАТОР ============================
# =============================================================================

async def is_bot_mentioned_or_private(message: types.Message, bot_info: types.User) -> bool:
    """
    Універсальний фільтр, що перевіряє, чи звертаються до бота.
    """
    if message.chat.type == 'private':
        return True
    if message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id:
        return True
    if message.text:
        bot_username = f"@{bot_info.username}"
        return bot_username in message.text or any(
            name.lower() in message.text.lower() for name in BOT_NAMES
        )
    return False

@general_router.message(
    is_bot_mentioned_or_private,
    F.text,
    ~CommandStart(),
    ~Command("go") # Команди обробляються окремо для чіткості
)
async def on_bot_interaction(message: types.Message, state: FSMContext, bot: Bot):
    """
    Єдиний "мозок" бота, що аналізує намір користувача і викликає потрібну логіку.
    """
    user_id = message.from_user.id
    current_time = time.time()

    # Перевірка кулдауну, щоб уникнути спаму
    if current_time - conversational_cooldown_cache[user_id] < CONVERSATIONAL_COOLDOWN_SECONDS:
        logger.info(f"Кулдаун для користувача {user_id}. Повідомлення проігноровано.")
        return
    conversational_cooldown_cache[user_id] = current_time

    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            # Крок 1: Визначення наміру
            intent_data = await gpt.determine_intent(message.text)
            intent = intent_data.get("intent", "unknown")
            
            logger.info(f"AI-маршрутизатор визначив намір: '{intent}' для повідомлення: '{message.text[:50]}...'")

            # Крок 2: Маршрутизація
            if intent == "create_lobby":
                await _start_party_creation(message, state)
            elif intent == "ask_question":
                await _handle_question(message, bot)
            elif intent == "general_chat":
                await _handle_general_chat(message, state, bot)
            else: # intent == "unknown" або інший
                logger.warning(f"Не вдалося визначити чіткий намір. Перехід до загальної розмови.")
                await _handle_general_chat(message, state, bot)

    except Exception as e:
        logger.error(f"Критична помилка в AI-маршрутизаторі: {e}", exc_info=True)
        await message.reply("Ой, мій внутрішній компас зламався. Не можу зрозуміти, що робити. Спробуйте ще раз.")
        await state.clear()


# =============================================================================
# ================== ІНШІ ОБРОБНИКИ (КОМАНДИ, FSM) ==========================
# =============================================================================

# Обробник команди /go залишається для прямого доступу до питань
@general_router.message(Command("go"))
async def cmd_go(message: types.Message, bot: Bot):
    """Обробляє явну команду /go для постановки питання."""
    # Видаляємо саму команду з тексту, щоб передати чистий запит
    query = message.text.replace("/go", "", 1).strip()
    if not query:
        await message.reply("Будь ласка, напишіть ваше питання після команди /go.")
        return
    
    # Створюємо "фейкове" повідомлення, щоб перевикористати існуючу логіку
    message.text = query
    await _handle_question(message, bot)

@general_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    # ... (код cmd_start залишається без змін) ...
    pass

# Всі обробники для FSM (вибір розміру паті, ролі і т.д.) залишаються без змін,
# оскільки вони реагують на callback-и, а не на текстові повідомлення.
# @general_router.callback_query(...)

async def error_handler(event: types.ErrorEvent, bot: Bot):
    # ... (код error_handler залишається без змін) ...
    pass

def register_general_handlers(dp: Dispatcher):
    """Реєструє всі загальні обробники в головному диспетчері."""
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (v4.0 - AI Router) успішно зареєстровано.")

# ... (тут має бути решта коду, що відповідає за обробку callback-ів від кнопок паті)
# async def on_party_creation_cancel(...) і т.д.
