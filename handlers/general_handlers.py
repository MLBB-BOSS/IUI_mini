import html
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Deque, List
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

# Імпорти з проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks

# === СХОВИЩЕ ІСТОРІЇ ДІАЛОГІВ ===
# Використовуємо defaultdict для автоматичного створення deque для нових чатів.
# deque з maxlen - ефективна структура для зберігання останніх N повідомлень.
chat_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(
    lambda: deque(maxlen=MAX_CHAT_HISTORY_LENGTH)
)

# Створюємо роутер для загальних обробників
general_router = Router()


@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """Обробник команди /start. Надсилає вітальне повідомлення з зображенням."""
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
    """Обробник команди /go. Надсилає запит до GPT та відповідь частинами, якщо потрібно."""
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
        # Спроба надіслати фінальне повідомлення про помилку
        pass


@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    """
    Обробляє звичайні текстові повідомлення, шукає в них тригери
    і генерує контекстну відповідь від AI.
    """
    if not message.text or message.text.startswith('/'):
        return # Ігноруємо команди та порожні повідомлення

    text_lower = message.text.lower()
    chat_id = message.chat.id
    user = message.from_user
    user_name = user.first_name if user else "Друже"

    # Завжди оновлюємо історію поточним повідомленням для повноти контексту
    chat_histories[chat_id].append({"role": "user", "content": message.text})

    # Шукаємо відповідний тригер
    matched_trigger_mood = None
    for trigger, mood in CONVERSATIONAL_TRIGGERS.items():
        if trigger in text_lower:
            matched_trigger_mood = mood
            logger.info(f"В чаті {chat_id} знайдено тригер '{trigger}' від '{user_name}'.")
            break # Знайшли перший, виходимо

    if matched_trigger_mood:
        try:
            # Передаємо копію історії в сервіс, щоб уникнути race conditions
            history_for_api = list(chat_histories[chat_id])

            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                reply_text = await gpt.generate_conversational_reply(
                    user_name=user_name,
                    chat_history=history_for_api,
                    trigger_mood=matched_trigger_mood
                )

            if reply_text and "<i>" not in reply_text: # Проста перевірка на повідомлення про помилку від сервісу
                # Додаємо відповідь бота в історію
                chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
                await message.reply(reply_text)
                logger.info(f"Надіслано розмовну відповідь в чат {chat_id}.")
            elif reply_text:
                 logger.warning(f"Сервіс повернув повідомлення, схоже на помилку, для чату {chat_id}: {reply_text}")
            else:
                 logger.error(f"Сервіс повернув порожню відповідь для чату {chat_id}.")

        except Exception as e:
            logger.exception(f"Помилка під час обробки тригерного повідомлення в чаті {chat_id}: {e}")


async def error_handler(update_event: Update, exception: Exception, bot: Bot):
    """Глобальний обробник помилок."""
    logger.error(f"Глобальна помилка в error_handler: {exception} для update: {update_event.model_dump_json(exclude_none=True)}", exc_info=True)

    chat_id: Optional[int] = None
    user_name: str = "друже"

    if update_event.message and update_event.message.chat:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = html.escape(update_event.message.from_user.first_name or "Гравець")
    elif update_event.callback_query and update_event.callback_query.message and update_event.callback_query.message.chat:
        chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = html.escape(update_event.callback_query.from_user.first_name or "Гравець")
        try:
            await update_event.callback_query.answer("Сталася помилка...", show_alert=False)
        except Exception: pass

    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину."

    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді користувачу.")


def register_general_handlers(dp: Dispatcher):
    """
    Реєструє всі загальні обробники команд та повідомлень.
    """
    # Підключаємо роутер до головного диспетчера
    dp.include_router(general_router)
    logger.info("Загальні обробники (команди та тригери) зареєстровано.")