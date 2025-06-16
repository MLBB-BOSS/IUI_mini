import html
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext


# Імпорти з проєкту
# Потрібно буде налаштувати правильні шляхи після остаточної структури
from config import ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger # Використовуємо logger з config
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks
# from ..config import ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger # Приклад відносного імпорту
# from ..services.openai_service import MLBBChatGPT
# from ..utils.message_utils import send_message_in_chunks


# Ініціалізація логера для цього файлу, якщо не використовується глобальний
# logger = logging.getLogger(__name__)

async def cmd_start(message: Message, state: FSMContext, bot: Bot): # Додано bot для використання в send_message_in_chunks
    """Обробник команди /start. Надсилає вітальне повідомлення з зображенням."""
    await state.clear() # Очищаємо стан, якщо він був
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
        # Використовуємо bot переданий в аргументах або bot з message.bot
        await message.answer_photo(
            photo=WELCOME_IMAGE_URL,
            caption=welcome_caption,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Привітання з зображенням для {user_name_escaped} надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітальне фото для {user_name_escaped}: {e}. Спроба надіслати текст.")
        # Формуємо резервний текст без фото
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


async def cmd_go(message: Message, state: FSMContext, bot: Bot): # Додано bot для send_message_in_chunks
    """Обробник команди /go. Надсилає запит до GPT та відповідь частинами, якщо потрібно."""
    await state.clear() # Очищаємо стан, якщо він був
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    # Вилучаємо команду /go та зайві пробіли
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

    # Повідомлення про обробку
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
    response_text = f"Вибач, {user_name_escaped}, сталася непередбачена помилка при генерації відповіді. 😔" # Default error
    try:
        # Використовуємо OPENAI_API_KEY з конфігурації
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}' від {user_name_escaped}: {e}")
        # response_text вже встановлено на повідомлення про помилку

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}' від {user_name_escaped}: {processing_time:.2f}с")

    admin_info = ""
    # Використовуємо ADMIN_USER_ID з конфігурації
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.8 GPT (gpt-4.1)</i>" # Версію можна також винести в конфіг

    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(
            bot_instance=bot, # Використовуємо переданий екземпляр бота
            chat_id=message.chat.id,
            text=full_response_to_send,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
        logger.info(f"Відповідь /go для {user_name_escaped} успішно надіслано (можливо, частинами).")
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /go для {user_name_escaped} навіть частинами: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді. Спробуйте пізніше. (Код: GO_SEND_FAIL)"
            if thinking_msg:
                 try:
                    await thinking_msg.edit_text(final_error_msg, parse_mode=None)
                 except TelegramAPIError: 
                    await message.reply(final_error_msg, parse_mode=None)
            else: 
                await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err_send:
            logger.error(f"Зовсім не вдалося надіслати фінальне повідомлення про помилку для {user_name_escaped}: {final_err_send}")

async def error_handler(update_event: Update, exception: Exception, bot: Bot): # Додано bot
    """Глобальний обробник помилок."""
    logger.error(f"Глобальна помилка в error_handler: {exception} для update: {update_event.model_dump_json(exclude_none=True)}", exc_info=True)

    chat_id: Optional[int] = None
    user_name: str = "друже" # Default user name

    # Спробуємо отримати chat_id та user_name з різних типів апдейтів
    if update_event.message and update_event.message.chat:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = html.escape(update_event.message.from_user.first_name or "Гравець")
    elif update_event.callback_query and update_event.callback_query.message and update_event.callback_query.message.chat:
        chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = html.escape(update_event.callback_query.from_user.first_name or "Гравець")
        try:
            # Підтверджуємо отримання колбеку, щоб прибрати "завантаження" у клієнта
            await update_event.callback_query.answer("Сталася помилка...", show_alert=False)
        except Exception: pass # Ігноруємо, якщо відповідь на колбек не вдалася

    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину або дві."

    if chat_id:
        try:
            # Використовуємо переданий екземпляр бота
            await bot.send_message(chat_id, error_message_text, parse_mode=None) # Надсилаємо як простий текст
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді користувачу.")

# Функція для реєстрації обробників цього файлу
def register_general_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_go, Command("go"))
    # Глобальний обробник помилок реєструється в dp.errors.register
    # dp.errors.register(error_handler) # Це буде зроблено в main.py
    logger.info("Загальні обробники зареєстровано.")
