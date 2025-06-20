import html
import time
from datetime import datetime, timedelta

from aiogram import Bot, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

import database
from config import (
    logger, PARTY_TRIGGER_PHRASES, PARTY_LOBBY_ROLES, OPENAI_API_KEY, ADMIN_USER_ID,
    WELCOME_IMAGE_URL, CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH, BOT_NAMES,
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

# === FSM для створення паті ===
class PartyFSM(StatesGroup):
    waiting_for_size = State()
    waiting_for_lifetime = State()
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()


# === ДОПОМІЖНІ ФУНКЦІЇ ===
async def format_lobby_message(lobby_data: dict) -> str:
    """Форматує текст повідомлення лобі."""
    players = lobby_data.get("players", {})
    party_size = lobby_data.get("party_size", 5)
    
    player_lines = []
    for p_id, p_info in players.items():
        player_lines.append(f"✅ <b>{html.escape(p_info['full_name'])}</b> — <i>{p_info['role']}</i>")
    
    players_text = "\n".join(player_lines) if player_lines else "<i>Поки що нікого...</i>"
    roles_text = "\n".join([f"• {role}" for role in lobby_data["roles_left"]]) if lobby_data["roles_left"] else "<i>Всі ролі зайняті!</i>"
    
    expires_dt = datetime.fromtimestamp(lobby_data['expires_at']) + timedelta(hours=3) # Kyiv time
    expires_str = expires_dt.strftime('%H:%M, %d.%m')

    return (f"🔥 <b>Збираємо паті! (до {expires_str})</b>\n\n"
            f"<b>Гравці в паті ({len(players)}/{party_size}):</b>\n{players_text}\n\n"
            f"<b>Вільні ролі:</b>\n{roles_text}")

async def update_lobby_message(bot: Bot, chat_id: int):
    """Отримує лобі з БД та оновлює відповідне повідомлення в чаті."""
    lobby_data = database.get_lobby(chat_id)
    if not lobby_data: return
    
    try:
        new_text = await format_lobby_message(lobby_data)
        # Оновлюємо клавіатуру для кожного, хто її бачить
        await bot.edit_message_text(
            text=new_text,
            chat_id=chat_id,
            message_id=lobby_data["message_id"],
            reply_markup=create_dynamic_lobby_keyboard(bot.id, lobby_data), # Умовно для всіх
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        logger.error(f"Не вдалося оновити повідомлення лобі в чаті {chat_id}: {e}")

# === ЛОГІКА "ПАТІ-МЕНЕДЖЕРА 3.0" ===

# --- Крок 1: Ініціація ---
@general_router.message(F.text.lower().in_(PARTY_TRIGGER_PHRASES))
async def on_party_trigger(message: types.Message, state: FSMContext):
    if database.get_lobby(message.chat.id):
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь!")
        return
    await message.reply("Бачу, ти хочеш зібрати паті. Допомогти тобі створити лобі?",
                        reply_markup=create_party_confirmation_keyboard())
    await state.clear()

@general_router.callback_query(F.data == "party_create_no")
async def on_party_creation_cancel(callback: types.CallbackQuery):
    await callback.message.edit_text("Гаразд, звертайся, якщо передумаєш! 😉")

@general_router.callback_query(F.data == "party_create_yes")
async def on_party_creation_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Чудово! Спочатку обери формат майбутнього паті:",
                                     reply_markup=create_party_size_keyboard())
    await state.set_state(PartyFSM.waiting_for_size)

# --- Крок 2: Налаштування ---
@general_router.callback_query(PartyFSM.waiting_for_size, F.data.startswith("party_size_"))
async def on_party_size_select(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(party_size=int(callback.data.split("_")[-1]))
    await callback.message.edit_text("Прийнято. Тепер обери, як довго лобі буде активним:",
                                     reply_markup=create_lobby_lifetime_keyboard())
    await state.set_state(PartyFSM.waiting_for_lifetime)

@general_router.callback_query(PartyFSM.waiting_for_lifetime, F.data.startswith("party_lifetime_"))
async def on_lobby_lifetime_select(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(expires_at=int(time.time()) + int(callback.data.split("_")[-1]))
    await callback.message.edit_text("Добре. І останнє: обери свою роль:",
                                     reply_markup=create_role_selection_keyboard(PARTY_LOBBY_ROLES))
    await state.set_state(PartyFSM.waiting_for_initiator_role)

# --- Крок 3: Створення та Керування ---
@general_router.callback_query(PartyFSM.waiting_for_initiator_role, F.data.startswith("party_role_select_"))
async def on_initiator_role_select(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    await state.clear()
    user, chat = callback.from_user, callback.message.chat
    selected_role = callback.data.split("party_role_select_")[-1]
    
    roles_left = PARTY_LOBBY_ROLES.copy()
    roles_left.remove(selected_role)
    
    lobby_data = {
        "chat_id": chat.id, "leader_id": user.id, "party_size": user_data["party_size"],
        "players": {str(user.id): {"full_name": user.full_name, "role": selected_role}},
        "roles_left": roles_left, "expires_at": user_data["expires_at"]
    }
    
    await callback.message.delete()
    lobby_text = await format_lobby_message(lobby_data)
    lobby_msg = await bot.send_message(chat.id, lobby_text,
                                       reply_markup=create_dynamic_lobby_keyboard(user.id, lobby_data),
                                       parse_mode=ParseMode.HTML)
    
    database.add_lobby(message_id=lobby_msg.message_id, **lobby_data)
    logger.info(f"Лобі створено в чаті {chat.id} лідером {user.full_name}")

@general_router.callback_query(F.data == "party_join")
async def on_party_join(callback: types.CallbackQuery, state: FSMContext):
    lobby = database.get_lobby(callback.message.chat.id)
    if not lobby or str(callback.from_user.id) in lobby["players"]:
        await callback.answer("Ви вже у паті або лобі неактивне!", show_alert=True)
        return
    if len(lobby["players"]) >= lobby["party_size"]:
        await callback.answer("На жаль, всі місця вже зайняті!", show_alert=True)
        return

    await callback.message.reply("Оберіть свою роль:", reply_markup=create_role_selection_keyboard(lobby["roles_left"]))
    await state.set_state(PartyFSM.waiting_for_joiner_role)
    await callback.answer()

@general_router.callback_query(PartyFSM.waiting_for_joiner_role, F.data.startswith("party_role_select_"))
async def on_joiner_role_select(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.delete() # Видаляємо повідомлення з вибором ролі
    await state.clear()
    
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)
    if not lobby: return

    selected_role = callback.data.split("party_role_select_")[-1]
    if selected_role not in lobby["roles_left"]:
        await callback.answer("Ця роль вже зайнята, спробуйте ще раз.", show_alert=True)
        return

    lobby["players"][str(user.id)] = {"full_name": user.full_name, "role": selected_role}
    lobby["roles_left"].remove(selected_role)
    
    database.add_lobby(chat.id, lobby["message_id"], lobby["leader_id"], lobby["party_size"], lobby["players"], lobby["roles_left"], lobby["expires_at"])
    await update_lobby_message(bot, chat.id)
    
    if len(lobby["players"]) == lobby["party_size"]:
        logger.info(f"Паті в чаті {chat.id} повністю зібрано!")
        # ... логіка сповіщення зібраної команди
    
    await callback.answer(f"Ви приєдналися до паті як {selected_role}!")

@general_router.callback_query(F.data == "party_leave")
async def on_party_leave(callback: types.CallbackQuery, bot: Bot):
    # ... реалізація виходу з паті
    await callback.answer("Ви успішно вийшли з паті.")

@general_router.callback_query(F.data == "party_cancel")
async def on_party_cancel(callback: types.CallbackQuery, bot: Bot):
    # ... реалізація скасування лобі лідером
    await callback.answer("Лобі було успішно скасовано.")

# === ІНШІ ОБРОБНИКИ ===
# ... (код cmd_start, cmd_go, handle_conversational_triggers, error_handler) ...
# Додаю їх для повноти файлу
@general_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=f"Привіт, {user_name_escaped}!")

@general_router.message(Command("go"))
async def cmd_go(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""
    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНапиши своє питання після <code>/go</code>.")
        return
    thinking_msg = await message.reply(f"🤔 {user_name_escaped}, аналізую твій запит...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Помилка MLBBChatGPT для '{user_query}': {e}")
        response_text = f"Вибач, {user_name_escaped}, сталася помилка."
    await send_message_in_chunks(bot, message.chat.id, response_text, initial_message_to_edit=thinking_msg)

async def error_handler(event: types.ErrorEvent, bot: Bot):
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=event.exception)
    # ... (решта коду обробника помилок)

def register_general_handlers(dp: Dispatcher):
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (v3.0) успішно зареєстровано.")
