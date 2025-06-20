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
from aiogram.types import Message, Update, CallbackQuery, User
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

# Імпорти з проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH, BOT_NAMES,
    CONVERSATIONAL_COOLDOWN_SECONDS, PARTY_TRIGGER_PHRASES,
    PARTY_LOBBY_ROLES, PARTY_LOBBY_COOLDOWN_SECONDS
)
from keyboards.inline_keyboards import create_party_lobby_keyboard
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks

# === СХОВИЩА ДАНИХ ДЛЯ КЕРУВАННЯ СТАНОМ ===
chat_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque(maxlen=MAX_CHAT_HISTORY_LENGTH))
chat_cooldowns: Dict[str, float] = {}  # Використовуємо рядкові ключі для розрізнення типів кулдаунів
active_lobbies: Dict[int, Dict[str, Any]] = {} # Сховище для активних лобі в кожному чаті

general_router = Router()

# === БЛОК ОБРОБНИКІВ КОМАНД ===

@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /start. Надсилає вітальне повідомлення."""
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    logger.info(f"Користувач {user_name_escaped} (ID: {user.id}) запустив бота.")
    
    # ... (решта коду cmd_start без змін, для стислості)
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
    """Обробник команди /go. Надсилає запит до GPT."""
    # ... (код cmd_go без змін, для стислості)
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
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Помилка MLBBChatGPT для '{user_query}': {e}")
        response_text = f"Вибач, {user_name_escaped}, сталася помилка."
    processing_time = time.time() - start_time
    admin_info = f"\n\n<i>⏱ {processing_time:.2f}с</i>" if user_id == ADMIN_USER_ID else ""
    await send_message_in_chunks(bot, message.chat.id, f"{response_text}{admin_info}", ParseMode.HTML, thinking_msg)


# === ГОЛОВНИЙ МАРШРУТИЗАТОР ТЕКСТОВИХ ПОВІДОМЛЕНЬ ===

@general_router.message(F.text)
async def handle_text_messages(message: Message, bot: Bot):
    """
    Головний обробник текстових повідомлень.
    Визначає намір користувача і передає управління відповідній функції.
    """
    if not message.text or message.text.startswith('/') or not message.from_user:
        return

    text_lower = message.text.lower()
    # Пріоритет №1: Перевірка на створення паті
    if any(phrase in text_lower for phrase in PARTY_TRIGGER_PHRASES):
        await handle_party_request(message, bot)
    # Пріоритет №2: Перевірка на розмовні тригери
    else:
        await handle_conversational_triggers(message, bot)

# === БЛОК ЛОГІКИ "ПАТІ-МЕНЕДЖЕРА" ===

async def handle_party_request(message: Message, bot: Bot):
    """
    Створює нове лобі для пошуку паті, застосовуючи кулдаун.
    """
    chat_id = message.chat.id
    user = message.from_user
    current_time = time.time()
    cooldown_key = f"party_{chat_id}"

    if chat_id in active_lobbies:
        await message.reply("☝️ В цьому чаті вже йде активний пошук паті. Приєднуйтесь до існуючого лобі!")
        return

    if (current_time - chat_cooldowns.get(cooldown_key, 0)) < PARTY_LOBBY_COOLDOWN_SECONDS:
        await message.reply("⏳ Зачекайте хвилину перед створенням нового лобі, будь ласка.")
        return

    logger.info(f"Користувач {user.full_name} ініціював пошук паті в чаті {chat_id}.")
    
    lobby_text = (f"🔥 <b>Збираємо паті!</b>\n\nІніціатор: {html.escape(user.full_name)}\n\n"
                  f"<b>Вільні ролі:</b>\n" + "\n".join([f"• {role}" for role in PARTY_LOBBY_ROLES]))
    
    lobby_message = await message.answer(lobby_text, reply_markup=create_party_lobby_keyboard(), parse_mode=ParseMode.HTML)

    active_lobbies[chat_id] = {
        "message_id": lobby_message.message_id,
        "initiator": user,
        "players": [],
        "roles_left": PARTY_LOBBY_ROLES.copy()
    }
    chat_cooldowns[cooldown_key] = current_time

@general_router.callback_query(F.data == "join_party")
async def on_join_party(callback_query: CallbackQuery, bot: Bot):
    """
    Обробляє натискання кнопки 'Приєднатися' до паті, оновлює лобі.
    """
    user = callback_query.from_user
    chat_id = callback_query.message.chat.id
    lobby = active_lobbies.get(chat_id)

    if not lobby:
        await callback_query.answer("На жаль, це лобі вже неактивне.", show_alert=True)
        return

    if any(p.id == user.id for p in lobby["players"]) or lobby["initiator"].id == user.id:
        await callback_query.answer("Ви вже у цьому паті!", show_alert=True)
        return

    if not lobby["roles_left"]:
        await callback_query.answer("Всі місця вже зайняті!", show_alert=True)
        return

    # Додаємо гравця і забираємо роль
    lobby["players"].append(user)
    lobby["roles_left"].pop(0)
    logger.info(f"Гравець {user.full_name} приєднався до паті в чаті {chat_id}.")
    
    # Формуємо оновлений текст
    all_players = [lobby["initiator"]] + lobby["players"]
    players_text = "\n".join([f"✅ <a href='tg://user?id={p.id}'>{html.escape(p.full_name)}</a>" for p in all_players])
    roles_text = "\n".join([f"• {role}" for role in lobby["roles_left"]]) if lobby["roles_left"] else "<i>Всі ролі зайняті!</i>"
    updated_text = (f"🔥 <b>Збираємо паті!</b>\n\n<b>Гравці в паті ({len(all_players)}/5):</b>\n{players_text}\n\n"
                    f"<b>Залишились ролі:</b>\n{roles_text}")

    if not lobby["roles_left"]: # Паті зібрано
        logger.info(f"Паті в чаті {chat_id} повністю зібрано!")
        await bot.edit_message_text(f"{updated_text}\n\n<b>✅ Паті зібрано! Готуйтесь до бою!</b>",
                                    chat_id, lobby["message_id"], reply_markup=None, parse_mode=ParseMode.HTML)
        
        final_call_text = (f"⚔️ <b>Команда зібрана! Всі в лобі!</b>\n\n" +
                           " ".join([f"<a href='tg://user?id={p.id}'>{html.escape(p.first_name)}</a>" for p in all_players]) +
                           f"\n\nGL HF! 🚀")
        await bot.send_message(chat_id, final_call_text, parse_mode=ParseMode.HTML)
        del active_lobbies[chat_id]
    else: # Паті ще збирається
        await bot.edit_message_text(updated_text, chat_id, lobby["message_id"], reply_markup=create_party_lobby_keyboard(), parse_mode=ParseMode.HTML)
    
    await callback_query.answer()

# === БЛОК ЛОГІКИ АДАПТИВНОГО СПІЛКУВАННЯ ===

async def handle_conversational_triggers(message: Message, bot: Bot):
    """
    Обробляє розмовні тригери за "Стратегією Адаптивної Присутності".
    """
    # ... (код handle_conversational_triggers без змін, для стислості)
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
    if is_explicit_mention or is_reply_to_bot or is_name_mention:
        should_respond = True
    else:
        cooldown_key = f"conv_{chat_id}"
        if (current_time - chat_cooldowns.get(cooldown_key, 0)) > CONVERSATIONAL_COOLDOWN_SECONDS:
            should_respond = True
            chat_cooldowns[cooldown_key] = current_time
    if should_respond:
        chat_histories[chat_id].append({"role": "user", "content": message.text})
        try:
            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                reply_text = await gpt.generate_conversational_reply(user_name, list(chat_histories[chat_id]), matched_trigger_mood)
            if reply_text and "<i>" not in reply_text:
                chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
                await message.reply(reply_text)
        except Exception as e:
            logger.exception(f"Помилка генерації адаптивної відповіді в чаті {chat_id}: {e}")

# === БЛОК ОБРОБКИ ПОМИЛОК ТА РЕЄСТРАЦІЇ ===

async def error_handler(event: types.ErrorEvent, bot: Bot):
    """Глобальний обробник помилок, сумісний з aiogram 3.x."""
    # ... (код error_handler без змін, для стислості)
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=event.exception)
    chat_id: Optional[int] = None
    user_name = "друже"
    update = event.update
    if update.message and update.message.chat:
        chat_id = update.message.chat.id
        if update.message.from_user: user_name = html.escape(update.message.from_user.first_name or "Гравець")
    elif update.callback_query and update.callback_query.message and update.callback_query.message.chat:
        chat_id = update.callback_query.message.chat.id
        if update.callback_query.from_user: user_name = html.escape(update.callback_query.from_user.first_name or "Гравець")
        try: await update.callback_query.answer("Сталася помилка...", show_alert=True)
        except TelegramAPIError: pass
    if chat_id:
        try: await bot.send_message(chat_id, f"Вибач, {user_name}, сталася непередбачена системна помилка 😔")
        except TelegramAPIError: pass


def register_general_handlers(dp: Dispatcher):
    """Реєструє всі загальні обробники у головному диспетчері."""
    dp.include_router(general_router)
    logger.info("✅ Загальні обробники (команди, паті-менеджер та адаптивні тригери) успішно зареєстровано.")
