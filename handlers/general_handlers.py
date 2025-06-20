import html
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Deque, List, Any
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, Update, CallbackQuery, User
from aiogram.exceptions import TelegramAPIError

# Імпорти з проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger, BOT_NAMES,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH, CONVERSATIONAL_COOLDOWN_SECONDS,
    PARTY_TRIGGER_PHRASES, PARTY_LOBBY_ROLES, PARTY_LOBBY_COOLDOWN_SECONDS
)
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard, create_role_selection_keyboard,
    create_party_lobby_keyboard
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks

# === СХОВИЩА ДАНИХ ТА FSM ===
chat_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque(maxlen=MAX_CHAT_HISTORY_LENGTH))
chat_cooldowns: Dict[str, float] = {}
active_lobbies: Dict[int, Dict[str, Any]] = {}

class PartyCreation(StatesGroup):
    waiting_for_initiator_role = State()
    waiting_for_joiner_role = State()

general_router = Router()

# === РЕЄСТРАЦІЯ ОБРОБНИКІВ В ПРАВИЛЬНОМУ ПОРЯДКУ ===

# 1. Обробники команд (найвищий пріоритет)
@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    # ... (код з попередньої версії)
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    logger.info(f"Користувач {user_name_escaped} (ID: {user.id}) запустив бота.")
    kyiv_tz = timezone(timedelta(hours=3))
    current_time_kyiv = datetime.now(kyiv_tz)
    current_hour = current_time_kyiv.hour
    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else "Доброго дня" if 12 <= current_hour < 17 else "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
    emoji = "🌅" if 5 <= current_hour < 12 else "☀️" if 12 <= current_hour < 17 else "🌆" if 17 <= current_hour < 22 else "🌙"
    welcome_caption = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}\n\nЛаскаво просимо до <b>MLBB IUI mini</b>! 🎮\nЯ твій AI-помічник для всього, що стосується світу Mobile Legends.\n\nГотовий допомогти тобі стати справжньою легендою!\n\n<b>Що я можу для тебе зробити:</b>\n🔸 Проаналізувати скріншот твого ігрового профілю.\n🔸 Відповісти на запитання по грі.\n\n👇 Для початку роботи, використай одну з команд:\n• <code>/analyzeprofile</code> – для аналізу скріншота.\n• <code>/go &lt;твоє питання&gt;</code> – для консультації (наприклад, <code>/go найкращий танк</code>)."""
    try:
        await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=welcome_caption, parse_mode=ParseMode.HTML)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото для {user_name_escaped}: {e}. Відправка тексту.")
        await message.answer(welcome_caption, parse_mode=ParseMode.HTML)


@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    # ... (код з попередньої версії)
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""
    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНапиши своє питання після <code>/go</code>.")
        return
    thinking_msg = await message.reply(f"🤔 {user_name_escaped}, аналізую твій запит...")
    start_time = time.time()
    try:
        async with MLBBChatGPT() as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Помилка MLBBChatGPT для '{user_query}': {e}")
        response_text = f"Вибач, {user_name_escaped}, сталася помилка."
    processing_time = time.time() - start_time
    admin_info = f"\n\n<i>⏱ {processing_time:.2f}с</i>" if user_id == ADMIN_USER_ID else ""
    await send_message_in_chunks(bot, message.chat.id, f"{response_text}{admin_info}", parse_mode=ParseMode.HTML, initial_message_to_edit=thinking_msg)


# 2. Обробник текстових повідомлень (ловить все, що не є командою)
@general_router.message(F.text)
async def handle_text_messages(message: Message, bot: Bot, state: FSMContext):
    # ... (код з попередньої версії)
    text_lower = message.text.lower()
    if any(phrase in text_lower for phrase in PARTY_TRIGGER_PHRASES):
        await handle_party_request(message, bot, state)
    else:
        await handle_conversational_triggers(message, bot)


# === БЛОК ЛОГІКИ "ПАТІ-МЕНЕДЖЕРА 2.0" (з попередньої версії) ===
async def handle_party_request(message: Message, bot: Bot, state: FSMContext):
    # ... (код з попередньої версії)
    chat_id = message.chat.id
    cooldown_key = f"party_{chat_id}"
    if chat_id in active_lobbies:
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь!")
        return
    if (time.time() - chat_cooldowns.get(cooldown_key, 0)) < PARTY_LOBBY_COOLDOWN_SECONDS:
        await message.reply("⏳ Зачекайте хвилину перед створенням нового лобі.")
        return
    await message.reply("Бачу, ти хочеш зібрати паті. Допомогти тобі створити лобі?",
                        reply_markup=create_party_confirmation_keyboard())


@general_router.callback_query(F.data == "party_create_no")
async def on_party_creation_no(callback_query: CallbackQuery):
    # ... (код з попередньої версії)
    await callback_query.message.edit_text("Гаразд, звертайся, якщо передумаєш! 😉")
    await callback_query.answer()


@general_router.callback_query(F.data == "party_create_yes")
async def on_party_creation_yes(callback_query: CallbackQuery, state: FSMContext):
    # ... (код з попередньої версії)
    await callback_query.message.edit_text(
        "Супер! Обері свою роль, щоб я міг створити лобі:",
        reply_markup=create_role_selection_keyboard(PARTY_LOBBY_ROLES)
    )
    await state.set_state(PartyCreation.waiting_for_initiator_role)
    await callback_query.answer()


@general_router.callback_query(PartyCreation.waiting_for_initiator_role, F.data.startswith("party_role_select_"))
async def on_initiator_role_select(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    # ... (код з попередньої версії)
    await state.clear()
    user = callback_query.from_user
    chat_id = callback_query.message.chat.id
    selected_role = callback_query.data.split("party_role_select_")[1]
    
    logger.info(f"Ініціатор {user.full_name} обрав роль '{selected_role}' в чаті {chat_id}.")

    roles_left = PARTY_LOBBY_ROLES.copy()
    roles_left.remove(selected_role)
    
    players_data = {user.id: {"user": user, "role": selected_role}}
    
    players_text = f"✅ <b>{html.escape(user.full_name)}</b> — <i>{selected_role}</i>"
    roles_text = "\n".join([f"• {role}" for role in roles_left])

    lobby_message_text = (f"🔥 <b>Збираємо паті!</b>\n\n"
                          f"<b>Гравці в паті (1/5):</b>\n{players_text}\n\n"
                          f"<b>Вільні ролі:</b>\n{roles_text}")
    
    await callback_query.message.edit_text("✅ Лобі створено!")
    lobby_message = await bot.send_message(chat_id, lobby_message_text,
                                           reply_markup=create_party_lobby_keyboard(), parse_mode=ParseMode.HTML)

    active_lobbies[chat_id] = {"message_id": lobby_message.message_id, "players": players_data, "roles_left": roles_left}
    chat_cooldowns[f"party_{chat_id}"] = time.time()
    await callback_query.answer()


@general_router.callback_query(F.data == "join_party")
async def on_join_party(callback_query: CallbackQuery, state: FSMContext):
    # ... (код з попередньої версії)
    user = callback_query.from_user
    chat_id = callback_query.message.chat.id
    lobby = active_lobbies.get(chat_id)

    if not lobby:
        await callback_query.answer("На жаль, це лобі вже неактивне.", show_alert=True); return
    if user.id in lobby["players"]:
        await callback_query.answer("Ви вже у цьому паті!", show_alert=True); return
    if not lobby["roles_left"]:
        await callback_query.answer("Всі місця вже зайняті!", show_alert=True); return

    role_request_msg = await callback_query.message.reply(
        f"<a href='tg://user?id={user.id}'>{html.escape(user.first_name)}</a>, обери свою роль:",
        reply_markup=create_role_selection_keyboard(lobby['roles_left']), parse_mode=ParseMode.HTML)
    
    await state.set_state(PartyCreation.waiting_for_joiner_role)
    await state.update_data(role_request_message_id=role_request_msg.message_id)
    await callback_query.answer()


@general_router.callback_query(PartyCreation.waiting_for_joiner_role, F.data.startswith("party_role_select_"))
async def on_joiner_role_select(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    # ... (код з попередньої версії)
    user = callback_query.from_user
    chat_id = callback_query.message.chat.id
    selected_role = callback_query.data.split("party_role_select_")[1]
    
    data = await state.get_data()
    await state.clear()

    if role_request_message_id := data.get("role_request_message_id"):
        try: await bot.delete_message(chat_id, role_request_message_id)
        except TelegramAPIError: logger.warning("Не вдалося видалити повідомлення із запитом ролі.")

    lobby = active_lobbies.get(chat_id)
    if not lobby or user.id in lobby["players"] or selected_role not in lobby["roles_left"]:
        await callback_query.answer("Щось пішло не так або ця роль вже зайнята. Спробуйте ще раз.", show_alert=True); return

    logger.info(f"Гравець {user.full_name} приєднався до паті в чаті {chat_id} з роллю '{selected_role}'.")
    lobby["players"][user.id] = {"user": user, "role": selected_role}
    lobby["roles_left"].remove(selected_role)
    
    players_text = "\n".join([f"✅ <b>{html.escape(p['user'].full_name)}</b> — <i>{p['role']}</i>" for p in lobby["players"].values()])
    roles_text = "\n".join([f"• {role}" for role in lobby["roles_left"]]) if lobby["roles_left"] else "<i>Всі ролі зайняті!</i>"
    
    updated_text = (f"🔥 <b>Збираємо паті!</b>\n\n"
                    f"<b>Гравці в паті ({len(lobby['players'])}/5):</b>\n{players_text}\n\n"
                    f"<b>Вільні ролі:</b>\n{roles_text}")

    if not lobby["roles_left"]:
        logger.info(f"Паті в чаті {chat_id} повністю зібрано!")
        await bot.edit_message_text(f"{updated_text}\n\n<b>✅ Паті зібрано! Готуйтесь до бою!</b>",
                                    chat_id, lobby["message_id"], reply_markup=None, parse_mode=ParseMode.HTML)
        
        final_call_text = (f"⚔️ <b>Команда зібрана! Всі в лобі!</b>\n\n" +
                           " ".join([f"<a href='tg://user?id={p['user'].id}'>{html.escape(p['user'].first_name)}</a>" for p in lobby['players'].values()]) +
                           f"\n\nGL HF! 🚀")
        await bot.send_message(chat_id, final_call_text, parse_mode=ParseMode.HTML)
        del active_lobbies[chat_id]
    else:
        await bot.edit_message_text(updated_text, chat_id, lobby["message_id"],
                                    reply_markup=create_party_lobby_keyboard(), parse_mode=ParseMode.HTML)
    await callback_query.answer()


async def handle_conversational_triggers(message: Message, bot: Bot):
    # ... (код з попередньої версії)
    text_lower = message.text.lower()
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    current_time = time.time()
    bot_info = await bot.get_me()
    is_explicit_mention = f"@{bot_info.username.lower()}" in text_lower
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_name_mention = any(re.search(r'\b' + name + r'\b', text_lower) for name in BOT_NAMES)
    matched_trigger_mood = None
    for trigger, mood in CONVERSATIONAL_TRIGGERS.items():
        if re.search(r'\b' + re.escape(trigger) + r'\b', text_lower):
            matched_trigger_mood = mood
            break
    if is_reply_to_bot and not matched_trigger_mood: matched_trigger_mood = "Користувач відповів на твоє повідомлення. Підтримай розмову."
    if not matched_trigger_mood: return
    should_respond = False
    cooldown_key = f"conv_{chat_id}"
    if is_explicit_mention or is_reply_to_bot or is_name_mention:
        should_respond = True
    else:
        if (current_time - chat_cooldowns.get(cooldown_key, 0)) > CONVERSATIONAL_COOLDOWN_SECONDS:
            should_respond = True
            chat_cooldowns[cooldown_key] = current_time
    if should_respond:
        chat_histories[chat_id].append({"role": "user", "content": message.text})
        try:
            async with MLBBChatGPT() as gpt:
                reply_text = await gpt.generate_conversational_reply(user_name, list(chat_histories[chat_id]), matched_trigger_mood)
            if reply_text and "<i>" not in reply_text:
                chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
                await message.reply(reply_text)
        except Exception as e:
            logger.exception(f"Помилка генерації адаптивної відповіді в чаті {chat_id}: {e}")


def register_general_handlers(dp: Dispatcher):
    """Реєструє всі загальні обробники у головному диспетчері."""
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (команди, паті-менеджер 2.0 та адаптивні тригери) успішно зареєстровано.")
