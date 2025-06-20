"""
Обробники для загальних команд та основної логіки "Паті-менеджера".

Цей модуль містить логіку для:
- Створення, управління та видалення ігрових лобі.
- Обробки стартових та інформаційних команд (/start, /go).
- Реалізації розмовного AI на базі OpenAI.
- Глобальної обробки помилок.
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
from utils.message_utils import send_message_in_chunks

general_router = Router()

# =============================================================================
# ======================== FINITE STATE MACHINES (FSM) ========================
# =============================================================================

class PartyFSM(StatesGroup):
    """Стани для процесу створення ігрового лобі."""
    waiting_for_size = State()
    waiting_for_lifetime = State()
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()

class ConversationalFSM(StatesGroup):
    """Стан для ведення безперервного діалогу з користувачем."""
    chatting = State()

# Кеш для відстеження часу останньої взаємодії в розмовному режимі
conversational_cooldown_cache: Dict[int, float] = defaultdict(float)


# =============================================================================
# ============================ HELPER FUNCTIONS ===============================
# =============================================================================

async def format_lobby_message(lobby_data: Dict[str, Any]) -> str:
    """
    Форматує текстове представлення ігрового лобі.

    Args:
        lobby_data: Словник з даними лобі з бази даних.

    Returns:
        Відформатований рядок для відправки в повідомленні.
    """
    players = lobby_data.get("players", {})
    party_size = lobby_data.get("party_size", 5)
    
    player_lines = [
        f"✅ <b>{html.escape(p['full_name'])}</b> — <i>{p['role']}</i>"
        for p in players.values()
    ]
    players_text = "\n".join(player_lines) if player_lines else "<i>Поки що нікого...</i>"
    
    roles_left = lobby_data.get("roles_left", [])
    roles_text = "\n".join([f"• {role}" for role in roles_left]) if roles_left else "<i>Всі ролі зайняті!</i>"
    
    # Переконуємось, що expires_at існує, інакше ставимо поточний час
    expires_at = lobby_data.get('expires_at', time.time())
    expires_dt = datetime.fromtimestamp(expires_at, tz=timezone(timedelta(hours=3))) # Kyiv time
    expires_str = expires_dt.strftime('%H:%M, %d.%m')
    
    return (
        f"🔥 <b>Збираємо паті! (до {expires_str})</b>\n\n"
        f"<b>Гравці в паті ({len(players)}/{party_size}):</b>\n{players_text}\n\n"
        f"<b>Вільні ролі:</b>\n{roles_text}"
    )

async def update_lobby_message(bot: Bot, chat_id: int, user_id: int | None = None):
    """
    Оновлює існуюче повідомлення лобі з актуальними даними.

    Args:
        bot: Екземпляр `Bot`.
        chat_id: ID чату, де знаходиться повідомлення лобі.
        user_id: (Опціонально) ID користувача, що ініціював оновлення.
                 Потрібно для коректного відображення динамічної клавіатури.
    """
    lobby_data = database.get_lobby(chat_id)
    if not lobby_data or "message_id" not in lobby_data:
        return

    try:
        new_text = await format_lobby_message(lobby_data)
        # Якщо user_id не передано, використовуємо 0 для "нейтрального" вигляду клавіатури
        keyboard_user_id = user_id if user_id is not None else 0
        
        await bot.edit_message_text(
            text=new_text,
            chat_id=chat_id,
            message_id=lobby_data["message_id"],
            reply_markup=create_dynamic_lobby_keyboard(keyboard_user_id, lobby_data),
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        if "message to edit not found" in str(e).lower() or "message is not modified" in str(e).lower():
            logger.warning(f"Спроба оновити неіснуюче або незмінене повідомлення лобі в чаті {chat_id}.")
        else:
            logger.error(f"Не вдалося оновити повідомлення лобі в чаті {chat_id}: {e}")
            # Якщо повідомлення видалено, видаляємо лобі з БД
            if "message to edit not found" in str(e).lower():
                database.remove_lobby(chat_id)


# =============================================================================
# ========================= LOBBY MANAGER HANDLERS ============================
# =============================================================================

@general_router.message(F.text.lower().in_(PARTY_TRIGGER_PHRASES))
async def on_party_trigger(message: types.Message, state: FSMContext):
    """Реагує на тригерні фрази для створення паті."""
    if database.get_lobby(message.chat.id):
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь!")
        return
    await message.reply(
        "Бачу, ти хочеш зібрати паті. Допомогти тобі створити лобі?",
        reply_markup=create_party_confirmation_keyboard()
    )
    await state.clear()

@general_router.callback_query(F.data == "party_create_no")
async def on_party_creation_cancel(callback: types.CallbackQuery):
    """Обробляє відмову від створення лобі."""
    await callback.message.edit_text("Гаразд, звертайся, якщо передумаєш! 😉")
    await callback.answer()

@general_router.callback_query(F.data == "party_create_yes")
async def on_party_creation_start(callback: types.CallbackQuery, state: FSMContext):
    """Починає процес створення лобі, запитуючи розмір паті."""
    await callback.message.edit_text(
        "Чудово! Спочатку обери формат майбутнього паті:",
        reply_markup=create_party_size_keyboard()
    )
    await state.set_state(PartyFSM.waiting_for_size)
    await callback.answer()

@general_router.callback_query(PartyFSM.waiting_for_size, F.data.startswith("party_size_"))
async def on_party_size_select(callback: types.CallbackQuery, state: FSMContext):
    """Обробляє вибір розміру паті та запитує час життя лобі."""
    await state.update_data(party_size=int(callback.data.split("_")[-1]))
    await callback.message.edit_text(
        "Прийнято. Як довго лобі буде активним:",
        reply_markup=create_lobby_lifetime_keyboard()
    )
    await state.set_state(PartyFSM.waiting_for_lifetime)
    await callback.answer()

@general_router.callback_query(PartyFSM.waiting_for_lifetime, F.data.startswith("party_lifetime_"))
async def on_lobby_lifetime_select(callback: types.CallbackQuery, state: FSMContext):
    """Обробляє вибір часу життя лобі та запитує роль ініціатора."""
    lifetime_seconds = int(callback.data.split("_")[-1])
    await state.update_data(expires_at=int(time.time()) + lifetime_seconds)
    await callback.message.edit_text(
        "Добре. І останнє: обери свою роль:",
        reply_markup=create_role_selection_keyboard(PARTY_LOBBY_ROLES)
    )
    await state.set_state(PartyFSM.waiting_for_initiator_role)
    await callback.answer()

@general_router.callback_query(PartyFSM.waiting_for_initiator_role, F.data.startswith("party_role_select_"))
async def on_initiator_role_select(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    """Завершує створення лобі після вибору ролі ініціатором."""
    user_data = await state.get_data()
    await state.clear()

    user, chat = callback.from_user, callback.message.chat
    selected_role = callback.data.split("party_role_select_")[-1]
    
    roles_left = [r for r in PARTY_LOBBY_ROLES if r != selected_role]
    
    lobby_data = {
        "chat_id": chat.id,
        "leader_id": user.id,
        "party_size": user_data["party_size"],
        "players": {str(user.id): {"full_name": user.full_name, "role": selected_role}},
        "roles_left": roles_left,
        "expires_at": user_data["expires_at"]
    }

    await callback.message.delete()
    
    lobby_text = await format_lobby_message(lobby_data)
    lobby_msg = await bot.send_message(
        chat.id,
        lobby_text,
        reply_markup=create_dynamic_lobby_keyboard(user.id, lobby_data),
        parse_mode=ParseMode.HTML
    )
    
    # Додаємо message_id до даних перед збереженням
    lobby_data["message_id"] = lobby_msg.message_id
    database.add_lobby(**lobby_data)
    logger.info(f"Лідер {user.full_name} (ID: {user.id}) створив нове лобі в чаті {chat.id}.")
    await callback.answer()

@general_router.callback_query(F.data == "party_join")
async def on_party_join(callback: types.CallbackQuery, state: FSMContext):
    """Ініціює процес приєднання до існуючого лобі."""
    lobby = database.get_lobby(callback.message.chat.id)
    user_id_str = str(callback.from_user.id)

    if not lobby or user_id_str in lobby["players"] or len(lobby["players"]) >= lobby["party_size"]:
        await callback.answer("Ви вже у паті, або лобі заповнене/неактивне!", show_alert=True)
        return
        
    if not lobby.get("roles_left"):
        await callback.answer("На жаль, вільних ролей не залишилось.", show_alert=True)
        return

    # Відповідаємо на callback, щоб прибрати "годинник"
    await callback.answer()
    
    # Надсилаємо тимчасове повідомлення із запитом ролі
    await callback.message.reply(
        f"{html.escape(callback.from_user.first_name)}, оберіть свою роль:",
        reply_markup=create_role_selection_keyboard(lobby["roles_left"]),
        # Бажано зробити це повідомлення "самознищуваним" або видаляти його потім
    )
    await state.set_state(PartyFSM.waiting_for_joiner_role)


@general_router.callback_query(PartyFSM.waiting_for_joiner_role, F.data.startswith("party_role_select_"))
async def on_joiner_role_select(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    """Завершує процес приєднання гравця до лобі."""
    # Видаляємо тимчасове повідомлення з вибором ролі
    try:
        await callback.message.delete()
    except TelegramAPIError:
        logger.warning("Не вдалося видалити тимчасове повідомлення вибору ролі.")

    await state.clear()
    
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)
    if not lobby: return

    selected_role = callback.data.split("party_role_select_")[-1]
    if selected_role not in lobby.get("roles_left", []):
        await callback.answer("Ця роль вже зайнята або недоступна.", show_alert=True)
        return

    lobby["players"][str(user.id)] = {"full_name": user.full_name, "role": selected_role}
    lobby["roles_left"].remove(selected_role)
    
    database.add_lobby(**lobby)
    await update_lobby_message(bot, chat.id, user.id)
    await callback.answer(f"Ви приєдналися до паті як {selected_role}!", show_alert=True)

    if len(lobby["players"]) >= lobby["party_size"]:
        logger.info(f"Команда в чаті {chat.id} повністю зібрана!")
        await bot.edit_message_reply_markup(chat.id, lobby["message_id"], reply_markup=None)
        
        leader_info = lobby["players"].get(str(lobby["leader_id"]))
        leader_mention = f"<a href='tg://user?id={lobby['leader_id']}'>{leader_info['full_name']}</a>" if leader_info else "Лідер"
        
        mentions = [
            f"<a href='tg://user?id={uid}'>{p_info['full_name']}</a>"
            for uid, p_info in lobby["players"].items()
        ]
        
        await bot.send_message(
            chat.id,
            f"⚔️ <b>Команда зібрана!</b>\nЛідер: {leader_mention}\nГравці: {', '.join(mentions)}\n\n<b>Усі в гру!</b>",
            parse_mode=ParseMode.HTML,
            reply_to_message_id=lobby["message_id"]
        )
        database.remove_lobby(chat.id)

@general_router.callback_query(F.data == "party_leave")
async def on_party_leave(callback: types.CallbackQuery, bot: Bot):
    """Обробляє вихід гравця з лобі."""
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)
    user_id_str = str(user.id)

    if not lobby or user_id_str not in lobby["players"]:
        await callback.answer("Ви не в цьому паті.", show_alert=True)
        return
        
    if user.id == lobby.get("leader_id"):
        await callback.answer("Лідер не може вийти, лише скасувати лобі.", show_alert=True)
        return

    removed_player_role = lobby["players"].pop(user_id_str)["role"]
    if removed_player_role not in lobby["roles_left"]:
        lobby["roles_left"].append(removed_player_role)
        
    database.add_lobby(**lobby)
    await update_lobby_message(bot, chat.id, user.id)
    await callback.answer("Ви успішно вийшли з паті.", show_alert=True)

@general_router.callback_query(F.data == "party_cancel")
async def on_party_cancel(callback: types.CallbackQuery, bot: Bot):
    """Обробляє скасування лобі його лідером."""
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)

    if not lobby or user.id != lobby.get("leader_id"):
        await callback.answer("Тільки лідер паті може скасувати лобі!", show_alert=True)
        return
        
    database.remove_lobby(chat.id)
    await callback.message.edit_text("🚫 <b>Лобі було скасовано його лідером.</b>")
    await callback.answer("Лобі успішно скасовано.")


# =============================================================================
# ========================== COMMAND HANDLERS =================================
# =============================================================================

@general_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """Обробляє команду /start, вітаючи користувача."""
    await state.clear()
    user_name = html.escape(message.from_user.first_name)
    welcome_text = (
        f"Привіт, <b>{user_name}</b>! Я твій AI-помічник для всього, що стосується світу Mobile Legends.\n\n"
        "<b>Що я можу:</b>\n"
        "• Створювати ігрові лобі (напиши 'го паті' в чаті).\n"
        "• Відповідати на твої запитання про гру (команда /go або просто згадай мене в чаті).\n"
        "• Аналізувати скріншоти (майбутня функція!).\n\n"
        "Просто почни спілкування, і я допоможу!"
    )
    try:
        # Спроба надіслати з картинкою, якщо не вийде - просто текст
        await message.answer_photo(WELCOME_IMAGE_URL, caption=welcome_text)
    except TelegramAPIError:
        await message.answer(welcome_text)

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
        await send_message_in_chunks(bot, message.chat.id, response, initial_message_to_edit=thinking_msg)
    except Exception as e:
        logger.error(f"Помилка в обробнику cmd_go: {e}", exc_info=True)
        await thinking_msg.edit_text("На жаль, сталася помилка під час обробки вашого запиту. 😔")


# =============================================================================
# ====================== CONVERSATIONAL AI HANDLERS ===========================
# =============================================================================

def is_bot_mentioned_or_private(message: types.Message, bot_info: types.User) -> bool:
    """
    Фільтр, що перевіряє, чи є чат приватним, або чи згадали бота в груповому чаті.
    """
    if message.chat.type == 'private':
        return True
    if message.text:
        # Перевірка згадки за @username або за іменем
        bot_username = f"@{bot_info.username}"
        return bot_username in message.text or any(name.lower() in message.text.lower() for name in BOT_NAMES)
    return False

@general_router.message(
    lambda msg: is_bot_mentioned_or_private(msg, bot.get_me()),
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

    # Перевірка кулдауну
    if current_time - conversational_cooldown_cache[user_id] < CONVERSATIONAL_COOLDOWN_SECONDS:
        # Можна додати якесь тихе повідомлення або просто ігнорувати
        logger.info(f"Кулдаун для користувача {user_id}. Повідомлення проігноровано.")
        return

    await state.set_state(ConversationalFSM.chatting)
    user_data = await state.get_data()
    history = user_data.get('history', [])
    
    # Додаємо поточне повідомлення до історії
    history.append({"role": "user", "content": message.text})
    
    # Обрізаємо історію, щоб не перевищувати ліміт
    if len(history) > MAX_CHAT_HISTORY_LENGTH:
        history = history[-MAX_CHAT_HISTORY_LENGTH:]

    thinking_msg = await message.reply("🤔 Думаю...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            # Передаємо всю історію для отримання контекстної відповіді
            response_text = await gpt.get_response_with_history(history)
        
        # Додаємо відповідь бота до історії
        history.append({"role": "assistant", "content": response_text})
        await state.update_data(history=history)

        await send_message_in_chunks(bot, message.chat.id, response_text, initial_message_to_edit=thinking_msg)
        
        # Оновлюємо час останньої взаємодії
        conversational_cooldown_cache[user_id] = current_time

    except Exception as e:
        logger.error(f"Помилка в розмовному обробнику: {e}", exc_info=True)
        await thinking_msg.edit_text("Ой, щось пішло не так. Спробуйте ще раз трохи пізніше.")
        await state.clear() # Скидаємо стан у разі помилки


# =============================================================================
# ============================= ERROR HANDLER =================================
# =============================================================================

async def error_handler(event: types.ErrorEvent, bot: Bot):
    """
    Глобальний обробник помилок. Логує винятки та повідомляє користувача.
    """
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=True)
    
    chat_id = None
    if event.update.callback_query:
        chat_id = event.update.callback_query.message.chat.id
        try:
            await event.update.callback_query.answer(
                "Сталася непередбачена помилка...", show_alert=True
            )
        except TelegramAPIError:
            pass # Якщо не можемо відповісти на callback, нічого страшного
    elif event.update.message:
        chat_id = event.update.message.chat.id

    if chat_id:
        try:
            await bot.send_message(
                chat_id,
                "😔 Вибачте, сталася непередбачена системна помилка. "
                "Я вже сповістив розробників, і вони все виправлять!"
            )
        except TelegramAPIError:
            logger.error(f"Не вдалося надіслати повідомлення про помилку в чат {chat_id}.")


# =============================================================================
# =========================== HANDLER REGISTRATION ============================
# =============================================================================

def register_general_handlers(dp: Dispatcher):
    """
    Реєструє всі загальні обробники в головному диспетчері.
    """
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (v3.1 - Conversational) успішно зареєстровано.")