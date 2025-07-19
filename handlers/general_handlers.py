"""
Головний модуль обробників загального призначення.

Цей файл містить всю логіку для:
- Обробки стартових команд (/start, /go, /search).
- Адаптивної відповіді на тригерні фрази в чаті.
- Універсального розпізнавання та обробки зображень.
- Глобальної обробки помилок.
- Встановлення списку команд для меню бота.

Архітектура побудована на роутері `general_router`, що обробляє
всі загальні команди, повідомлення та зображення.
Логіка створення паті винесена в окремий модуль `party_handler`.
"""
import html
import logging
import re
import time
import base64
import io
import random
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update, CallbackQuery, PhotoSize, BotCommand, BotCommandScopeDefault
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from openai import RateLimitError

# Імпорти з нашого проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH,
    BOT_NAMES, CONVERSATIONAL_COOLDOWN_SECONDS,
    VISION_AUTO_RESPONSE_ENABLED, VISION_RESPONSE_COOLDOWN_SECONDS, 
    VISION_MAX_IMAGE_SIZE_MB, VISION_CONTENT_EMOJIS, SEARCH_COOLDOWN_SECONDS
)
# Імпортуємо сервіси та утиліти
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks
from utils.formatter import format_bot_response
# 🧠 ІМПОРТУЄМО ФУНКЦІЇ ДЛЯ РОБОТИ З БД ТА НОВИМИ ШАРАМИ ПАМ'ЯТІ
from database.crud import get_user_settings, update_user_settings
from utils.session_memory import SessionData, load_session, save_session
from utils.cache_manager import load_user_cache, save_user_cache, clear_user_cache


# === СХОВИЩА ДАНИХ У ПАМ'ЯТІ ===
chat_cooldowns: dict[int, float] = {}
vision_cooldowns: dict[int, float] = {}
search_cooldowns: dict[int, float] = {}

# 🧠 Визначаємо тригери для завантаження повного профілю
PERSONALIZATION_TRIGGERS = [
    "мій ранг", "мої герої", "моїх героїв", "мої улюблені",
    "мій вінрейт", "моя стата", "мій профіль", "про мене"
]
# 💎 НОВЕ: Тригери для детальних запитів, які краще обробити через /go
DETAILED_REQUEST_TRIGGERS = [
    "порадь", "поясни", "розкажи", "гайд", "кого краще", "що краще",
    "як грати", "що збирати", "контрпік"
]


# === ІНІЦІАЛІЗАЦІЯ РОУТЕРІВ ТА КЛІЄНТІВ ===
general_router = Router()
# 🚀 Ініціалізуємо GPT клієнт для використання в різних обробниках
gpt_client = MLBBChatGPT(OPENAI_API_KEY)


# === ФУНКЦІЯ ДЛЯ ВСТАНОВЛЕННЯ КОМАНД БОТА ===
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🏁 Перезапустити та активувати бота"),
        BotCommand(command="profile", description="👤 Мій профіль (реєстрація/оновлення)"),
        BotCommand(command="go", description="💬 Задати питання AI-помічнику"),
        BotCommand(command="search", description="🔍 Пошук новин та оновлень"),
        BotCommand(command="analyzeprofile", description="📸 Аналіз скріншота профілю"),
        BotCommand(command="analyzestats", description="📊 Аналіз скріншота статистики"),
        BotCommand(command="settings", description="⚙️ Налаштування реакцій бота"),
        BotCommand(command="mute", description="🔇 Вимкнути всі реакції"),
        BotCommand(command="unmute", description="🔊 Увімкнути всі реакції"),
        BotCommand(command="help", description="❓ Допомога та інфо"),
    ]
    try:
        await bot.set_my_commands(commands, BotCommandScopeDefault())
        logger.info("✅ Список команд бота успішно оновлено.")
    except Exception as e:
        logger.error(f"Помилка під час оновлення команд бота: {e}", exc_info=True)

# === ДОПОМІЖНІ ФУНКЦІЇ ===
def get_user_display_name(user: types.User | None) -> str:
    if not user:
        return "друже"
    if user.first_name and user.first_name.strip():
        return html.escape(user.first_name.strip())
    elif user.username and user.username.strip():
        return html.escape(user.username.strip())
    else:
        return "друже"

# === ЗАГАЛЬНІ ОБРОБНИКИ КОМАНД ===
@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /start, який також знімає м'ют."""
    await state.clear()
    user = message.from_user
    if not user: return

    # ❗️ ЛОГІКА ЗНЯТТЯ М'ЮТУ ПРИ СТАРТІ
    settings = await get_user_settings(user.id)
    if settings.mute_chat and settings.mute_vision and settings.mute_party:
        logger.info(f"Користувач {user.id} використав /start, знімаю всі м'юти.")
        await update_user_settings(user.id, mute_chat=False, mute_vision=False, mute_party=False)
        await clear_user_cache(user.id)
    
    user_name_escaped = get_user_display_name(user)
    logger.info(f"Користувач {user_name_escaped} (ID: {user.id}) запустив бота /start.")
    kyiv_tz = timezone(timedelta(hours=3))
    current_hour = datetime.now(kyiv_tz).hour
    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else "Доброго дня" if 12 <= current_hour < 17 else "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
    emoji = "🌅" if 5 <= current_hour < 12 else "☀️" if 12 <= current_hour < 17 else "🌆" if 17 <= current_hour < 22 else "🌙"
    
    welcome_caption = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}

Ласкаво просимо до <b>GGenius</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.

<b>Що я можу для тебе зробити:</b>
🔸 Знайти найсвіжішу інформацію в Інтернеті!
🔸 Проаналізувати скріншот твого ігрового профілю.
🔸 Відповісти на запитання по грі.
🔸 Автоматично реагувати на зображення в чаті!

👇 Для початку роботи, використай одну з команд в меню або напиши її:
• <code>/search &lt;твій запит&gt;</code>
• <code>/go &lt;твоє питання&gt;</code>
• <code>/profile</code>
• Або просто надішли будь-яке зображення! 📸
"""
    try:
        await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=welcome_caption, parse_mode=ParseMode.HTML)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото-привітання: {e}. Відправляю текст.")
        await message.answer(welcome_caption, parse_mode=ParseMode.HTML)

@general_router.message(Command("help"))
async def cmd_help(message: Message):
    """Обробник команди /help."""
    help_text = """
ℹ️ <b>Довідка по боту GGenius</b>

Я - ваш AI-помічник для Mobile Legends. Ось список моїх основних команд:

/start - Перезапустити бота та показати вітальне повідомлення.
/profile - Зареєструвати або оновити свій ігровий профіль.
/go <code>&lt;питання&gt;</code> - Задати будь-яке питання про гру (герої, предмети, тактики).
/search <code>&lt;запит&gt;</code> - Знайти останні новини або інформацію в Інтернеті.
/analyzeprofile - Запустити аналіз скріншота вашого профілю.
/analyzestats - Запустити аналіз скріншота вашої статистики.
/settings - Відкрити меню налаштувань моїх реакцій.
/mute - Вимкнути мої автоматичні відповіді для вас.
/unmute - Увімкнути мої автоматичні відповіді.
/help - Показати це повідомлення.

Також я можу автоматично реагувати на зображення в чаті та підтримувати розмову, якщо ви звернетесь до мене.
"""
    await message.reply(help_text, parse_mode=ParseMode.HTML)

# 🚀 ОНОВЛЕНИЙ ОБРОБНИК /SEARCH
@general_router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    if not user: return
    user_name_escaped = get_user_display_name(user)
    user_id = user.id
    
    # 🚀 ЛОГІКА КУЛДАУНУ
    current_time = time.time()
    last_search_time = search_cooldowns.get(user_id, 0)
    
    if (current_time - last_search_time) < SEARCH_COOLDOWN_SECONDS:
        seconds_left = int(SEARCH_COOLDOWN_SECONDS - (current_time - last_search_time))
        await message.reply(f"⏳ Зачекай, будь ласка, ще {seconds_left} сек. перед наступним пошуком.")
        logger.warning(f"Користувач {user_name_escaped} (ID: {user_id}) намагається використати /search занадто часто.")
        return

    user_query = message.text.replace("/search", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив пошуковий запит: '{user_query}'")

    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 🔎\nНапиши запит після <code>/search</code>, наприклад:\n<code>/search останні зміни балансу героїв</code>", parse_mode=ParseMode.HTML)
        return

    thinking_msg = await message.reply(f"🛰️ {user_name_escaped}, шукаю найсвіжішу інформацію в Інтернеті...")
    start_time = time.time()
    
    async with gpt_client as gpt:
        response_text = await gpt.get_web_search_response(user_name_escaped, user_query)
    
    # 🚀 ОНОВЛЮЄМО ЧАС ОСТАННЬОГО ПОШУКУ
    search_cooldowns[user_id] = time.time()
    
    processing_time = time.time() - start_time
    logger.info(f"Час обробки /search для '{user_query}': {processing_time:.2f}с")

    if not response_text:
        response_text = f"Вибач, {user_name_escaped}, не вдалося отримати відповідь. Спробуй пізніше."
    else:
        # ❗️ НОВЕ: Замінюємо Markdown посилання на статичний текст
        link_pattern = re.compile(r'\(\[.*?\]\(https?://\S+\)\)')
        response_text = link_pattern.sub("🔗 Посилання", response_text)

    admin_info = ""
    # ❗️ FIX: Явне перетворення типів для надійного порівняння
    if int(user_id) == int(ADMIN_USER_ID):
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | OpenAI ({gpt_client.SEARCH_MODEL})</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(
            bot_instance=bot,
            chat_id=message.chat.id,
            text=full_response_to_send,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /search для {user_name_escaped}: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді."
            if thinking_msg: await thinking_msg.edit_text(final_error_msg, parse_mode=None)
            else: await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err:
             logger.error(f"Не вдалося надіслати навіть фінальне повідомлення про помилку: {final_err}")

@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    if not user: return
    user_name_escaped = get_user_display_name(user)
    user_id = user.id
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив запит /go: '{user_query}'")

    if not user_query:
        await message.reply(f"Привіт, <b>{user_name_escaped}</b>! 👋\nНапиши питання після <code>/go</code>, наприклад:\n<code>/go найкращі герої для міду</code>", parse_mode=ParseMode.HTML)
        return

    thinking_msg = await message.reply(random.choice([f"🤔 Аналізую запит...", f"🧠 Обробляю інформацію...", f"⏳ Хвилинку, шукаю відповідь..."]))
    start_time = time.time()

    response_text = f"Вибач, {user_name_escaped}, сталася помилка генерації відповіді. 😔"
    try:
        async with gpt_client as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}': {e}")

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}': {processing_time:.2f}с")

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | GPT ({gpt_client.TEXT_MODEL})</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(bot, message.chat.id, full_response_to_send, ParseMode.HTML, thinking_msg)
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /go: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді."
            if thinking_msg: await thinking_msg.edit_text(final_error_msg, parse_mode=None)
            else: await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err:
             logger.error(f"Не вдалося надіслати навіть фінальне повідомлення про помилку: {final_err}")

# ❗️ НОВІ ОБРОБНИКИ ДЛЯ /mute та /unmute
@general_router.message(Command("mute"))
async def cmd_mute(message: Message):
    """Обробник команди /mute, що вимикає всі автоматичні реакції."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    user_name = get_user_display_name(message.from_user)
    
    logger.info(f"Користувач {user_name} (ID: {user_id}) використав /mute.")
    success = await update_user_settings(
        user_id, mute_chat=True, mute_vision=True, mute_party=True
    )
    if success:
        await message.reply("🔇 Добре, я буду мовчати. Всі мої автоматичні реакції вимкнено.")
    else:
        await message.reply("Щось пішло не так, не вдалося зберегти налаштування. 😕")

@general_router.message(Command("unmute"))
async def cmd_unmute(message: Message):
    """Обробник команди /unmute, що вмикає всі автоматичні реакції."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    user_name = get_user_display_name(message.from_user)

    logger.info(f"Користувач {user_name} (ID: {user_id}) використав /unmute.")
    success = await update_user_settings(
        user_id, mute_chat=False, mute_vision=False, mute_party=False
    )
    if success:
        await message.reply("🔊 Я знову в грі! Всі мої автоматичні реакції увімкнено.")
    else:
        await message.reply("Щось пішло не так, не вдалося зберегти налаштування. 😕")


# === ОБРОБНИКИ ПОВІДОМЛЕНЬ (ФОТО ТА ТЕКСТ) ===
@general_router.message(F.photo)
async def handle_image_messages(message: Message, bot: Bot):
    if not VISION_AUTO_RESPONSE_ENABLED or not message.photo or not message.from_user:
        return

    user_id = message.from_user.id
    bot_info = await bot.get_me()
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id

    # ❗️ ОНОВЛЕНА ПЕРЕВІРКА СТАТУСУ М'ЮТУ
    settings = await get_user_settings(user_id)
    if settings.mute_vision:
        if is_reply_to_bot:
            logger.info(f"Користувач {user_id} з mute_vision=True відповів боту, знімаю м'ют vision.")
            await update_user_settings(user_id, mute_vision=False)
            await clear_user_cache(user_id)
            await message.reply("📸 Приємно знову бачити твої зображення! Реакції на фото увімкнено.")
        else:
            logger.info(f"Ігнорую зображення від {user_id}, оскільки mute_vision=True.")
            return

    chat_id = message.chat.id
    current_time = time.time()
    current_user_name = get_user_display_name(message.from_user)
    
    user_caption = message.caption or ""
    
    is_caption_mention = False
    if user_caption:
        is_caption_mention = (f"@{bot_info.username.lower()}" in user_caption.lower() or 
                            any(re.search(r'\b' + name + r'\b', user_caption.lower()) for name in BOT_NAMES))

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
        if not file_info or not file_info.file_path: return

        image_bytes_io = await bot.download_file(file_info.file_path)
        if not image_bytes_io: return

        image_base64 = base64.b64encode(image_bytes_io.read()).decode('utf-8')
        
        async with gpt_client as gpt:
            vision_response = await gpt.analyze_image_universal(
                image_base64, 
                current_user_name,
                caption_text=user_caption
            )

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
            
        elif thinking_msg:
            await thinking_msg.edit_text(f"Хм, {current_user_name}, не можу розібрати, що тут 🤔")
    except Exception as e:
        logger.exception(f"Помилка обробки зображення від {current_user_name}: {e}")
        if thinking_msg: await thinking_msg.delete()
        await message.reply(f"Упс, {current_user_name}, щось пішло не так з обробкою зображення 😅")

@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    if not message.text or message.text.startswith('/') or not message.from_user:
        return

    url_pattern = re.compile(r'https?://\S+')
    if url_pattern.search(message.text):
        logger.info(f"Повідомлення від {message.from_user.id} містить посилання і буде проігноровано.")
        return

    user_id = message.from_user.id
    bot_info = await bot.get_me()
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id

    # ❗️ ОНОВЛЕНА ПЕРЕВІРКА СТАТУСУ М'ЮТУ
    settings = await get_user_settings(user_id)
    if settings.mute_chat:
        if is_reply_to_bot:
            logger.info(f"Користувач {user_id} з mute_chat=True відповів боту, знімаю м'ют чату.")
            await update_user_settings(user_id, mute_chat=False)
            await clear_user_cache(user_id)
            await message.reply("🔊 Приємно знову спілкуватися! Автоматичні відповіді для вас увімкнено.")
        else:
            logger.info(f"Ігнорую текстовий тригер від {user_id}, оскільки mute_chat=True.")
            return

    text_lower = message.text.lower()
    chat_id = message.chat.id
    current_user_name = get_user_display_name(message.from_user)
    current_time = time.time()
    
    is_explicit_mention = f"@{bot_info.username.lower()}" in text_lower
    is_name_mention = any(re.search(r'\b' + name + r'\b', text_lower) for name in BOT_NAMES)

    # Перевірка наявності будь-якого тригера для активації
    is_trigger_present = next((True for trigger in CONVERSATIONAL_TRIGGERS if re.search(r'\b' + re.escape(trigger) + r'\b', text_lower)), False)
    
    # 💎 НОВЕ: Перевірка на детальний запит
    is_detailed_request = any(trigger in text_lower for trigger in DETAILED_REQUEST_TRIGGERS)
    
    if is_detailed_request:
        logger.info(f"Виявлено детальний запит від {current_user_name}. Пропоную використати /go.")
        original_query = message.text.replace(f"@{bot_info.username}", "").strip()
        await message.reply(
            f"🤔 {current_user_name}, це схоже на складне питання.\n"
            f"Для найкращої відповіді, будь ласка, використай команду /go:\n"
            f"<code>/go {html.escape(original_query)}</code>"
        )
        return

    if not (is_reply_to_bot or is_trigger_present):
        return

    should_respond = False
    if is_explicit_mention or is_reply_to_bot or is_name_mention:
        should_respond = True
    elif (current_time - chat_cooldowns.get(chat_id, 0)) > CONVERSATIONAL_COOLDOWN_SECONDS:
        should_respond = True
        chat_cooldowns[chat_id] = current_time

    if should_respond:
        is_personalization_request = any(trigger in text_lower for trigger in PERSONALIZATION_TRIGGERS)
        
        user_cache = await load_user_cache(user_id)
        is_registered = bool(user_cache)

        if not is_registered and is_personalization_request:
            logger.info(f"Незареєстрований користувач {current_user_name} спробував отримати персоналізовану відповідь.")
            await message.reply(
                f"Привіт, {current_user_name}! 👋\n\n"
                "Бачу, ти хочеш отримати персональну інформацію. Для цього мені потрібно знати твій профіль.\n\n"
                f"Будь ласка, пройди швидку реєстрацію за допомогою команди /profile. Це дозволить мені зберігати твою історію та надавати більш точні відповіді!"
            )
            return

        # Визначаємо, яку історію використовувати
        if is_registered:
            chat_history = user_cache.get('chat_history') if user_cache.get('chat_history') is not None else []
        else: 
            session = await load_session(user_id)
            chat_history = session.chat_history

        # Оновлюємо історію
        chat_history.append({"role": "user", "content": message.text})
        if len(chat_history) > MAX_CHAT_HISTORY_LENGTH:
            chat_history = chat_history[-MAX_CHAT_HISTORY_LENGTH:]

        try:
            async with gpt_client as gpt:
                # ❗️ FIX: Зберігаємо результат роботи санітайзера
                reply_text = await gpt.generate_conversational_reply(
                    user_id=user_id,
                    chat_history=chat_history
                )
            
            if reply_text:
                # ❗️ FIX: Додаємо в історію та зберігаємо в кеш саме очищену відповідь
                chat_history.append({"role": "assistant", "content": reply_text})
                
                # ❗️ ОНОВЛЕНА ЛОГІКА: Використання нового форматера
                formatted_message = format_bot_response(reply_text, content_type="default")
                
                if is_registered:
                    user_cache['chat_history'] = chat_history
                    await save_user_cache(user_id, user_cache)
                else:
                    session.chat_history = chat_history
                    await save_session(user_id, session)

                await message.reply(formatted_message)
        except Exception as e:
            logger.exception(f"Помилка генерації адаптивної відповіді: {e}")


# === ГЛОБАЛЬНИЙ ОБРОБНИК ПОМИЛОК (без змін) ===
async def error_handler(event: types.ErrorEvent, bot: Bot):
    logger.error(f"Глобальна помилка: {event.exception}", exc_info=event.exception)
    chat_id, user_name = None, "друже"
    update = event.update
    if update.message:
        chat_id = update.message.chat.id
        user_name = get_user_display_name(update.message.from_user)
    elif update.callback_query and update.callback_query.message:
        chat_id = update.callback_query.message.chat.id
        user_name = get_user_display_name(update.callback_query.from_user)
        try: await update.callback_query.answer("Сталася помилка...", show_alert=False)
        except TelegramAPIError: pass
    
    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔"
    if "TelegramAPIError" in str(event.exception):
        error_message_text = f"Упс, {user_name}, проблема з Telegram API 📡 Спробуй ще раз."
    
    if chat_id:
        try:
            # ❗️ ОНОВЛЕНА ЛОГІКА: Повідомлення про помилки також проходять через форматер
            formatted_error = format_bot_response(error_message_text, content_type="error")
            await bot.send_message(chat_id, formatted_error, parse_mode=ParseMode.HTML)
        except TelegramAPIError as e:
            logger.error(f"Не вдалося надіслати повідомлення про помилку в чат {chat_id}: {e}")

# === РЕЄСТРАЦІЯ ОБРОБНИКІВ ===
def register_general_handlers(dp: Dispatcher):
    """Реєструє всі загальні обробники (команди, тригери, Vision)."""
    dp.include_router(general_router)
    logger.info("🚀 Загальні обробники (команди, тригери, Vision) успішно зареєстровано.")
