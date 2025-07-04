"""
Головний модуль обробників загального призначення.

Цей файл містить всю логіку для:
- Обробки стартових команд (/start, /go, /search).
- Адаптивної відповіді на тригерні фрази в чаті.
- Покрокового створення ігрового лобі (паті) з використанням FSM.
- 🆕 Універсального розпізнавання та обробки зображень.
- Глобальної обробки помилок.

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
from aiogram.types import Message, Update, CallbackQuery, PhotoSize
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

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
from services.gemini_service import GeminiSearch # Новий сервіс для Gemini
from utils.message_utils import send_message_in_chunks
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard,
    create_role_selection_keyboard,
    create_dynamic_lobby_keyboard
)

# === ВИЗНАЧЕННЯ СТАНІВ FSM ===
class PartyCreationFSM(StatesGroup):
    """
    Стани для покрокового процесу створення паті.
    """
    waiting_for_confirmation = State()
    waiting_for_role_selection = State()

# === СХОВИЩА ДАНИХ У ПАМ'ЯТІ ===
chat_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque(maxlen=MAX_CHAT_HISTORY_LENGTH))
chat_cooldowns: Dict[int, float] = {}
vision_cooldowns: Dict[int, float] = {}
active_lobbies: Dict[str, Dict] = {}
ALL_ROLES: List[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]

# === ІНІЦІАЛІЗАЦІЯ РОУТЕРІВ ТА КЛІЄНТІВ ===
party_router = Router()
general_router = Router()
gemini_client = GeminiSearch()

# === ДОПОМІЖНІ ФУНКЦІЇ ===
def get_user_display_name(user: Optional[types.User]) -> str:
    """
    Витягує найкраще доступне ім'я користувача для звернення.
    Написано в розгорнутому стилі для максимальної читабельності.
    """
    if not user:
        return "друже"
    
    if user.first_name and user.first_name.strip():
        return html.escape(user.first_name.strip())
    elif user.username and user.username.strip():
        return html.escape(user.username.strip())
    else:
        return "друже"

def is_party_request_message(message: Message) -> bool:
    """
    Безпечна функція для визначення, чи є повідомлення запитом на створення паті.
    """
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

def get_lobby_message_text(lobby_data: dict) -> str:
    """
    Форматує текст повідомлення для лобі на основі поточних даних.
    """
    leader_name = html.escape(lobby_data['leader_name'])
    role_emoji_map = {"Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙", "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"}
    
    players_list = []
    taken_roles = [player_info['role'] for player_info in lobby_data['players'].values()]
    for player_id, player_info in lobby_data['players'].items():
        role = player_info['role']
        name = html.escape(player_info['name'])
        emoji = role_emoji_map.get(role, "🔹")
        players_list.append(f"• {emoji} <b>{role}:</b> {name}")

    available_roles_list = [f"• {role_emoji_map.get(r, '🔹')} {r}" for r in ALL_ROLES if r not in taken_roles]
    header = f"🔥 <b>Збираємо паті на рейтинг!</b> 🔥\n\n<b>Ініціатор:</b> {leader_name}\n"
    players_section = "<b>Учасники:</b>\n" + "\n".join(players_list)
    available_section = "\n\n<b>Вільні ролі:</b>\n" + "\n".join(available_roles_list) if available_roles_list else "\n\n✅ <b>Команда зібрана!</b>"
    return f"{header}\n{players_section}{available_section}"

# === ЛОГІКА СТВОРЕННЯ ПАТІ (FSM) ===
@party_router.message(F.text & F.func(is_party_request_message))
async def ask_for_party_creation(message: Message, state: FSMContext):
    user_name = get_user_display_name(message.from_user)
    logger.info(f"Виявлено запит на створення паті від {user_name}: '{message.text}'")
    await state.set_state(PartyCreationFSM.waiting_for_confirmation)
    await message.reply("Бачу, ти хочеш зібрати команду. Допомогти тобі?", reply_markup=create_party_confirmation_keyboard())

@party_router.callback_query(F.data == "party_cancel_creation")
async def cancel_party_creation(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Гаразд. Якщо передумаєш - звертайся! 😉")
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_confirmation, F.data == "party_start_creation")
async def prompt_for_role(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PartyCreationFSM.waiting_for_role_selection)
    await callback.message.edit_text("Чудово! Оберіть свою роль:", reply_markup=create_role_selection_keyboard(ALL_ROLES))
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_role_selection, F.data.startswith("party_role_select:"))
async def create_party_lobby(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user
    selected_role = callback.data.split(":")[-1]
    lobby_id = str(callback.message.message_id)
    lobby_data = {"leader_id": user.id, "leader_name": get_user_display_name(user), "players": {user.id: {"name": get_user_display_name(user), "role": selected_role}}, "chat_id": callback.message.chat.id}
    active_lobbies[lobby_id] = lobby_data
    logger.info(f"Створено лобі {lobby_id} ініціатором {get_user_display_name(user)} з роллю {selected_role}")
    message_text = get_lobby_message_text(lobby_data)
    keyboard = create_dynamic_lobby_keyboard(lobby_id, user.id, lobby_data)
    await callback.message.edit_text(message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer(f"Ви зайняли роль: {selected_role}")
    await state.clear()

# === ЗАГАЛЬНІ ОБРОБНИКИ КОМАНД ===
@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    user_name_escaped = get_user_display_name(user)
    logger.info(f"Користувач {user_name_escaped} (ID: {user.id}) запустив бота /start.")
    kyiv_tz = timezone(timedelta(hours=3))
    current_hour = datetime.now(kyiv_tz).hour
    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else "Доброго дня" if 12 <= current_hour < 17 else "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
    emoji = "🌅" if 5 <= current_hour < 12 else "☀️" if 12 <= current_hour < 17 else "🌆" if 17 <= current_hour < 22 else "🌙"
    
    welcome_caption = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}

Ласкаво просимо до <b>MLBB IUI mini</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.

<b>Що я можу для тебе зробити:</b>
🔸 Знайти найсвіжішу інформацію в Інтернеті!
🔸 Проаналізувати скріншот твого ігрового профілю.
🔸 Відповісти на запитання по грі.
🔸 Автоматично реагувати на зображення в чаті!

👇 Для початку роботи, використай одну з команд:
• <code>/search &lt;твій запит&gt;</code> – для пошуку новин та оновлень.
• <code>/go &lt;твоє питання&gt;</code> – для консультації по грі.
• <code>/analyzeprofile</code> – для аналізу скріншота.
• Або просто надішли будь-яке зображення! 📸
"""
    try:
        await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=welcome_caption, parse_mode=ParseMode.HTML)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото-привітання: {e}. Відправляю текст.")
        await message.answer(welcome_caption, parse_mode=ParseMode.HTML)

@general_router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    user_name_escaped = get_user_display_name(user)
    user_id = user.id if user else "невідомий"
    user_query = message.text.replace("/search", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив пошуковий запит: '{user_query}'")

    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 🔎\nНапиши запит після <code>/search</code>, наприклад:\n<code>/search останні зміни балансу героїв</code>", parse_mode=ParseMode.HTML)
        return

    thinking_msg = await message.reply(f"🛰️ {user_name_escaped}, шукаю найсвіжішу інформацію через Google...")
    start_time = time.time()
    
    response_text = await gemini_client.get_search_response(user_query, user_name_escaped)
    
    processing_time = time.time() - start_time
    logger.info(f"Час обробки /search для '{user_query}': {processing_time:.2f}с")

    if not response_text:
        response_text = f"Вибач, {user_name_escaped}, не вдалося отримати відповідь. Спробуй пізніше."

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | Gemini (gemini-1.5-flash)</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        # 🔽 ВИПРАВЛЕНО: Додано відсутній параметр parse_mode=ParseMode.HTML
        await send_message_in_chunks(
            bot_instance=bot,
            chat_id=message.chat.id,
            text=full_response_to_send,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /search для {user_name_escaped}: {e}", exc_info=True)
        # Розгорнута обробка помилки відправки
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді."
            if thinking_msg:
                await thinking_msg.edit_text(final_error_msg, parse_mode=None)
            else:
                await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err:
             logger.error(f"Не вдалося надіслати навіть фінальне повідомлення про помилку: {final_err}")

@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    user_name_escaped = get_user_display_name(user)
    user_id = user.id if user else "невідомий"
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив запит /go: '{user_query}'")

    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНапиши питання після <code>/go</code>, наприклад:\n<code>/go найкращі герої для міду</code>", parse_mode=ParseMode.HTML)
        return

    thinking_msg = await message.reply(random.choice([f"🤔 Аналізую запит...", f"🧠 Обробляю інформацію...", f"⏳ Хвилинку, шукаю відповідь..."]))
    start_time = time.time()

    response_text = f"Вибач, {user_name_escaped}, сталася помилка генерації відповіді. 😔"
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}': {e}")

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}': {processing_time:.2f}с")

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | GPT (gpt-4.1)</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(bot, message.chat.id, full_response_to_send, ParseMode.HTML, thinking_msg)
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /go: {e}", exc_info=True)
        # Розгорнута обробка помилки відправки
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді."
            if thinking_msg:
                await thinking_msg.edit_text(final_error_msg, parse_mode=None)
            else:
                await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err:
             logger.error(f"Не вдалося надіслати навіть фінальне повідомлення про помилку: {final_err}")

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
    is_caption_mention = False
    if message.caption:
        is_caption_mention = (f"@{bot_info.username.lower()}" in message.caption.lower() or any(re.search(r'\b' + name + r'\b', message.caption.lower()) for name in BOT_NAMES))

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
        if not file_info.file_path: return

        image_bytes = await bot.download_file(file_info.file_path)
        if not isinstance(image_bytes, io.BytesIO): return

        image_base64 = base64.b64encode(image_bytes.getvalue()).decode('utf-8')
        
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            vision_response = await gpt.analyze_image_universal(image_base64, current_user_name)

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
            
            chat_histories[chat_id].extend([{"role": "user", "content": "[Надіслав зображення]"}, {"role": "assistant", "content": final_response}])
        elif thinking_msg:
            await thinking_msg.edit_text(f"Хм, {current_user_name}, не можу розібрати, що тут 🤔")
    except Exception as e:
        logger.exception(f"Помилка обробки зображення від {current_user_name}: {e}")
        await message.reply(f"Упс, {current_user_name}, щось пішло не так з обробкою зображення 😅")

@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    if not message.text or message.text.startswith('/') or not message.from_user:
        return

    text_lower = message.text.lower()
    chat_id = message.chat.id
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
        chat_histories[chat_id].append({"role": "user", "content": message.text})
        try:
            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                reply_text = await gpt.generate_conversational_reply(current_user_name, list(chat_histories[chat_id]), matched_trigger_mood)
            if reply_text and "<i>" not in reply_text:
                chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
                await message.reply(reply_text)
        except Exception as e:
            logger.exception(f"Помилка генерації адаптивної відповіді: {e}")

# === ГЛОБАЛЬНИЙ ОБРОБНИК ПОМИЛОК ===
async def error_handler(event: types.ErrorEvent, bot: Bot):
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=event.exception)
    chat_id, user_name = None, "друже"
    update = event.update
    if update.message:
        chat_id = update.message.chat.id
        user_name = get_user_display_name(update.message.from_user)
    elif update.callback_query:
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
    dp.include_router(party_router)
    dp.include_router(general_router)
    logger.info("🚀 Обробники для паті, команд, тригерів та Vision успішно зареєстровано.")