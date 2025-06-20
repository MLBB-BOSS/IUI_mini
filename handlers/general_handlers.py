import html
import time
from datetime import datetime, timedelta
from typing import Dict, Any

from aiogram import Bot, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError

import database
from config import logger, PARTY_TRIGGER_PHRASES, PARTY_LOBBY_ROLES, OPENAI_API_KEY, WELCOME_IMAGE_URL
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard, create_party_size_keyboard,
    create_lobby_lifetime_keyboard, create_role_selection_keyboard,
    create_dynamic_lobby_keyboard
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks

general_router = Router()

class PartyFSM(StatesGroup):
    waiting_for_size = State()
    waiting_for_lifetime = State()
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()

# === ДОПОМІЖНІ ФУНКЦІЇ ===
async def format_lobby_message(lobby_data: dict) -> str:
    players = lobby_data.get("players", {})
    party_size = lobby_data.get("party_size", 5)
    player_lines = [f"✅ <b>{html.escape(p['full_name'])}</b> — <i>{p['role']}</i>" for p in players.values()]
    players_text = "\n".join(player_lines) if player_lines else "<i>Поки що нікого...</i>"
    roles_text = "\n".join([f"• {role}" for role in lobby_data["roles_left"]]) if lobby_data["roles_left"] else "<i>Всі ролі зайняті!</i>"
    expires_dt = datetime.fromtimestamp(lobby_data['expires_at']) + timedelta(hours=3)
    expires_str = expires_dt.strftime('%H:%M, %d.%m')
    return (f"🔥 <b>Збираємо паті! (до {expires_str})</b>\n\n"
            f"<b>Гравці в паті ({len(players)}/{party_size}):</b>\n{players_text}\n\n"
            f"<b>Вільні ролі:</b>\n{roles_text}")

async def update_lobby_message(bot: Bot, chat_id: int, user_id_for_keyboard: int):
    lobby_data = database.get_lobby(chat_id)
    if not lobby_data: return
    try:
        new_text = await format_lobby_message(lobby_data)
        await bot.edit_message_text(
            text=new_text, chat_id=chat_id, message_id=lobby_data["message_id"],
            reply_markup=create_dynamic_lobby_keyboard(user_id_for_keyboard, lobby_data),
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        logger.error(f"Не вдалося оновити повідомлення лобі в чаті {chat_id}: {e}")

# === ЛОГІКА "ПАТІ-МЕНЕДЖЕРА 3.0" ===
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

@general_router.callback_query(PartyFSM.waiting_for_size, F.data.startswith("party_size_"))
async def on_party_size_select(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(party_size=int(callback.data.split("_")[-1]))
    await callback.message.edit_text("Прийнято. Як довго лобі буде активним:",
                                     reply_markup=create_lobby_lifetime_keyboard())
    await state.set_state(PartyFSM.waiting_for_lifetime)

@general_router.callback_query(PartyFSM.waiting_for_lifetime, F.data.startswith("party_lifetime_"))
async def on_lobby_lifetime_select(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(expires_at=int(time.time()) + int(callback.data.split("_")[-1]))
    await callback.message.edit_text("Добре. І останнє: обери свою роль:",
                                     reply_markup=create_role_selection_keyboard(PARTY_LOBBY_ROLES))
    await state.set_state(PartyFSM.waiting_for_initiator_role)

@general_router.callback_query(PartyFSM.waiting_for_initiator_role, F.data.startswith("party_role_select_"))
async def on_initiator_role_select(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    await state.clear()
    user, chat = callback.from_user, callback.message.chat
    selected_role = callback.data.split("party_role_select_")[-1]
    roles_left = [r for r in PARTY_LOBBY_ROLES if r != selected_role]
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

@general_router.callback_query(F.data == "party_join")
async def on_party_join(callback: types.CallbackQuery, state: FSMContext):
    lobby = database.get_lobby(callback.message.chat.id)
    if not lobby or str(callback.from_user.id) in lobby["players"] or len(lobby["players"]) >= lobby["party_size"]:
        await callback.answer("Ви вже у паті, або лобі заповнене/неактивне!", show_alert=True)
        return
    await callback.message.reply("Оберіть свою роль:", reply_markup=create_role_selection_keyboard(lobby["roles_left"]))
    await state.set_state(PartyFSM.waiting_for_joiner_role)
    await callback.answer()

@general_router.callback_query(PartyFSM.waiting_for_joiner_role, F.data.startswith("party_role_select_"))
async def on_joiner_role_select(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.message.delete()
    await state.clear()
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)
    if not lobby: return
    selected_role = callback.data.split("party_role_select_")[-1]
    if selected_role not in lobby["roles_left"]:
        await callback.answer("Ця роль вже зайнята.", show_alert=True)
        return
    lobby["players"][str(user.id)] = {"full_name": user.full_name, "role": selected_role}
    lobby["roles_left"].remove(selected_role)
    database.add_lobby(**lobby)
    await update_lobby_message(bot, chat.id, user.id)
    await callback.answer(f"Ви приєдналися до паті як {selected_role}!")
    if len(lobby["players"]) == lobby["party_size"]:
        await bot.edit_message_reply_markup(chat.id, lobby["message_id"], reply_markup=None)
        mentions = [f"<a href='tg://user?id={uid}'>{p_info['full_name']}</a>" for uid, p_info in lobby["players"].items()]
        await bot.send_message(chat.id, f"⚔️ <b>Команда зібрана! Всі в лобі!</b>\n\n" + ", ".join(mentions), parse_mode=ParseMode.HTML)
        database.remove_lobby(chat.id)

@general_router.callback_query(F.data == "party_leave")
async def on_party_leave(callback: types.CallbackQuery, bot: Bot):
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)
    if not lobby or str(user.id) not in lobby["players"]:
        await callback.answer("Ви не перебуваєте в цьому паті!", show_alert=True)
        return
    removed_player_role = lobby["players"].pop(str(user.id))["role"]
    lobby["roles_left"].append(removed_player_role)
    database.add_lobby(**lobby)
    await update_lobby_message(bot, chat.id, user.id)
    await callback.answer("Ви успішно вийшли з паті.")

@general_router.callback_query(F.data == "party_cancel")
async def on_party_cancel(callback: types.CallbackQuery, bot: Bot):
    user, chat = callback.from_user, callback.message.chat
    lobby = database.get_lobby(chat.id)
    if not lobby or user.id != lobby["leader_id"]:
        await callback.answer("Тільки лідер паті може скасувати лобі!", show_alert=True)
        return
    database.remove_lobby(chat.id)
    await callback.message.edit_text("🚫 <b>Лобі було скасовано його лідером.</b>")
    await callback.answer("Лобі успішно скасовано.")

# === ІНШІ ОБРОБНИКИ ===
@general_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_name = html.escape(message.from_user.first_name)
    await message.answer_photo(WELCOME_IMAGE_URL, caption=f"Привіт, <b>{user_name}</b>! Я твій AI-помічник...")

@general_router.message(Command("go"))
async def cmd_go(message: types.Message, bot: Bot):
    user_name = html.escape(message.from_user.first_name)
    query = message.text.replace("/go", "").strip()
    if not query:
        await message.reply("Напишіть ваше питання після /go.")
        return
    thinking_msg = await message.reply("Аналізую ваш запит...")
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response = await gpt.get_response(user_name, query)
        await send_message_in_chunks(bot, message.chat.id, response, initial_message_to_edit=thinking_msg)
    except Exception as e:
        logger.error(f"Помилка в cmd_go: {e}")
        await thinking_msg.edit_text("Вибачте, сталася помилка.")

async def error_handler(event: types.ErrorEvent, bot: Bot):
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=True)
    if event.update.callback_query:
        await event.update.callback_query.answer("Сталася помилка...", show_alert=True)
        chat_id = event.update.callback_query.message.chat.id
    elif event.update.message:
        chat_id = event.update.message.chat.id
    else: return
    await bot.send_message(chat_id, "😔 Вибачте, сталася непередбачена системна помилка.")

def register_general_handlers(dp: Dispatcher):
    dp.include_router(general_router)
