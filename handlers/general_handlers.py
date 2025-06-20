import html
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Deque
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

# Імпорти з проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH,
    BOT_NAMES, CONVERSATIONAL_COOLDOWN_SECONDS
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks


# === СХОВИЩА ДАНИХ ДЛЯ КЕРУВАННЯ СТАНОМ ===
# Словник для зберігання історії повідомлень для кожного чату
chat_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(
    lambda: deque(maxlen=MAX_CHAT_HISTORY_LENGTH)
)
# Словник для відстеження часу останньої пасивної відповіді в кожному чаті
chat_cooldowns: Dict[int, float] = {}

# Створюємо роутер для всіх загальних обробників
general_router = Router()

@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """
    Обробник команди /start.
    Надсилає вітальне повідомлення з зображенням та описом функціоналу.
    """
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) запустив бота командою /start.")

    kyiv_tz = timezone(timedelta(hours=3))
    current_time_kyiv = datetime.now(kyiv_tz)
    current_hour = current_time_kyiv.hour

    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else \
                   "Доброго дня" if 12 <= current_hour < 17 else \
                   "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

    emoji = "🌅" if 5 <= current_hour < 12 else \
            "☀️" if 12 <= current_hour < 17 else \
            "🌆" if 17 <= current_hour < 22 else "🌙"

    welcome_caption = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}

Ласкаво просимо до <b>MLBB IUI mini</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.

Готовий допомогти тобі стати справжньою легендою!

<b>Що я можу для тебе зробити:</b>
🔸 Проаналізувати скріншот твого ігрового профілю.
🔸 Відповісти на запитання по грі.

👇 Для початку роботи, використай одну з команд:
• <code>/analyzeprofile</code> – для аналізу скріншота.
• <code>/go &lt;твоє питання&gt;</code> – для консультації (наприклад, <code>/go найкращий танк</code>).
"""

    try:
        await message.answer_photo(
            photo=WELCOME_IMAGE_URL,
            caption=welcome_caption,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Привітання з зображенням для {user_name_escaped} надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітальне фото для {user_name_escaped}: {e}. Спроба надіслати текст.")
        fallback_text = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}
Ласкаво просимо до <b>MLBB IUI mini</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.
Готовий допомогти тобі стати справжньою легендою!

<b>Що я можу для тебе зробити:</b>
🔸 Проаналізувати скріншот твого ігрового профілю (команда <code>/analyzeprofile</code>).
🔸 Відповісти на запитання по грі (команда <code>/go &lt;твоє питання&gt;</code>).
"""
        try:
            await message.answer(fallback_text, parse_mode=ParseMode.HTML)
            logger.info(f"Резервне текстове привітання для {user_name_escaped} надіслано.")
        except TelegramAPIError as e_text:
            logger.error(f"Не вдалося надіслати навіть резервне текстове привітання для {user_name_escaped}: {e_text}")


@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    """
    Обробник команди /go.
    Надсилає запит до GPT та повертає структуровану відповідь.
    """
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив запит з /go: '{user_query}'")

    if not user_query:
        logger.info(f"Порожній запит /go від {user_name_escaped}.")
        await message.reply(
            f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
            "Напиши своє питання після <code>/go</code>, наприклад:\n"
            "<code>/go найкращі герої для міду</code>"
        )
        return

    thinking_messages = [
        f"🤔 {user_name_escaped}, аналізую твій запит...",
        f"🧠 Обробляю інформацію, {user_name_escaped}, щоб дати кращу пораду!",
        f"⏳ Хвилинку, {user_name_escaped}, шукаю відповідь...",
    ]
    thinking_msg_text = thinking_messages[int(time.time()) % len(thinking_messages)]
    thinking_msg: Optional[Message] = None
    try:
        thinking_msg = await message.reply(thinking_msg_text)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати 'thinking_msg' для {user_name_escaped}: {e}")

    start_time = time.time()
    response_text = f"Вибач, {user_name_escaped}, сталася непередбачена помилка при генерації відповіді. 😔"
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}' від {user_name_escaped}: {e}")

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}' від {user_name_escaped}: {processing_time:.2f}с")

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.8 GPT (gpt-4.1)</i>"

    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(
            bot_instance=bot,
            chat_id=message.chat.id,
            text=full_response_to_send,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
        logger.info(f"Відповідь /go для {user_name_escaped} успішно надіслано (можливо, частинами).")
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /go для {user_name_escaped} навіть частинами: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді. Спробуйте пізніше."
            if thinking_msg:
                 try:
                    await thinking_msg.edit_text(final_error_msg, parse_mode=None)
                 except TelegramAPIError: 
                    await message.reply(final_error_msg, parse_mode=None)
            else: 
                await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err_send:
            logger.error(f"Зовсім не вдалося надіслати фінальне повідомлення про помилку для {user_name_escaped}: {final_err_send}")


@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    """
    Обробляє текстові повідомлення за "Стратегією Адаптивної Присутності",
    щоб бот поводився як розумний учасник чату, а не спамер.
    """
    if not message.text or message.text.startswith('/') or not message.from_user:
        return

    # --- 1. Збір даних для аналізу ---
    text_lower = message.text.lower()
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    current_time = time.time()
    bot_info = await bot.get_me()

    # --- 2. Визначення умов для відповіді (Рівні Пріоритету) ---
    is_explicit_mention = f"@{bot_info.username.lower()}" in text_lower
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_name_mention = any(re.search(r'\b' + name + r'\b', text_lower) for name in BOT_NAMES)

    # --- 3. Пошук тригера ---
    matched_trigger_mood = None
    for trigger, mood in CONVERSATIONAL_TRIGGERS.items():
        # Використовуємо регулярні вирази для пошуку цілих слів/фраз
        if re.search(r'\b' + re.escape(trigger) + r'\b', text_lower):
            matched_trigger_mood = mood
            break
    
    # Якщо це відповідь на повідомлення бота, але без конкретного тригера,
    # встановлюємо загальний "настрій" для продовження розмови.
    if is_reply_to_bot and not matched_trigger_mood:
        matched_trigger_mood = "Користувач відповів на твоє повідомлення. Підтримай розмову."

    # Якщо немає жодного тригера для реакції, виходимо.
    if not matched_trigger_mood:
        return

    # --- 4. Логіка прийняття фінального рішення про відповідь ---
    should_respond = False
    # Рівень 1 і 2: Пряме звернення або згадка імені - відповідаємо завжди.
    if is_explicit_mention or is_reply_to_bot or is_name_mention:
        should_respond = True
        logger.info(f"Прийнято рішення відповісти: пряме звернення в чаті {chat_id}.")
    # Рівень 3: Пасивний тригер - перевіряємо кулдаун.
    else:
        last_response_time = chat_cooldowns.get(chat_id, 0)
        if (current_time - last_response_time) > CONVERSATIONAL_COOLDOWN_SECONDS:
            should_respond = True
            chat_cooldowns[chat_id] = current_time  # Важливо: оновлюємо час останньої відповіді
            logger.info(f"Прийнято рішення відповісти: пасивний тригер в чаті {chat_id} (кулдаун пройшов).")
        else:
            logger.info(f"Рішення проігнорувати: пасивний тригер в чаті {chat_id} (активний кулдаун).")

    # --- 5. Генерація та відправка відповіді ---
    if should_respond:
        chat_histories[chat_id].append({"role": "user", "content": message.text})
        try:
            history_for_api = list(chat_histories[chat_id])
            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                reply_text = await gpt.generate_conversational_reply(
                    user_name=user_name,
                    chat_history=history_for_api,
                    trigger_mood=matched_trigger_mood
                )

            if reply_text and "<i>" not in reply_text:
                chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
                await message.reply(reply_text)
                logger.info(f"Адаптивну відповідь успішно надіслано в чат {chat_id}.")
            else:
                logger.error(f"Сервіс повернув порожню або помилкову відповідь для чату {chat_id}.")
        except Exception as e:
            logger.exception(f"Критична помилка під час генерації адаптивної відповіді в чаті {chat_id}: {e}")


async def error_handler(event: types.ErrorEvent, bot: Bot):
    """
    Глобальний обробник помилок, сумісний з aiogram 3.x.
    Логує помилку та надсилає повідомлення користувачу, якщо можливо.
    """
    logger.error(
        f"Глобальна помилка: {event.exception} для update: {event.update.model_dump_json(exclude_none=True, indent=2)}",
        exc_info=event.exception
    )

    chat_id: Optional[int] = None
    user_name: str = "друже"

    update = event.update
    if update.message and update.message.chat:
        chat_id = update.message.chat.id
        if update.message.from_user:
            user_name = html.escape(update.message.from_user.first_name or "Гравець")
    elif update.callback_query and update.callback_query.message and update.callback_query.message.chat:
        chat_id = update.callback_query.message.chat.id
        if update.callback_query.from_user:
            user_name = html.escape(update.callback_query.from_user.first_name or "Гравець")
        try:
            await update.callback_query.answer("Сталася помилка...", show_alert=False)
        except TelegramAPIError:
            pass

    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину."

    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except TelegramAPIError as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді користувачу.")


def register_general_handlers(dp: Dispatcher):
    """
    Реєструє всі загальні обробники команд та повідомлень у головному диспетчері.
    """
    dp.include_router(general_router)
    logger.info("Загальні обробники (команди та адаптивні тригери) успішно зареєстровано.")
