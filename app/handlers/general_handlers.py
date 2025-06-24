import logging
import os
from aiogram import Router, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ErrorEvent, User
from aiogram.utils.markdown import hbold, hcode, hitalic
from aiogram.exceptions import TelegramAPIError

from app.keyboards.reply_keyboards import get_main_kb

# Налаштування логера та роутера
logger = logging.getLogger(__name__)
general_router = Router()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

@general_router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обробник команди /start. Вітає користувача та пропонує головне меню.
    """
    user = message.from_user
    welcome_message = (
        f"Привіт, {hbold(user.full_name)}! 👋\n\n"
        f"Я — 🤖 {hbold('MLBB IUI mini')}, ваш персональний помічник у світі Mobile Legends: Bang Bang.\n\n"
        "Я можу аналізувати скріншоти з результатами матчів, надавати статистику та поради. "
        "Просто надішліть мені скріншот, і я зроблю все інше!\n\n"
        "Для початку, спробуйте команду /go."
    )
    await message.answer(welcome_message, reply_markup=get_main_kb())

@general_router.message(Command("go"))
async def cmd_go(message: Message):
    """
    Обробник команди /go. Інструктує користувача надіслати скріншот.
    """
    await message.answer("🚀 Команда /go отримана! Надсилайте скріншот для аналізу.")


async def general_error_handler(event: ErrorEvent, bot: Bot):
    """
    Глобальний обробник помилок для всіх неперехоплених винятків.

    Цей обробник реєструється в головному диспетчері. Він логує помилку
    та надсилає детальне сповіщення адміністратору, якщо його ID задано.
    """
    logger.error(f"Неочікувана помилка: {event.exception}", exc_info=True)

    if not ADMIN_USER_ID:
        logger.warning("ADMIN_USER_ID не встановлено. Сповіщення про помилку не буде надіслано.")
        return

    # Спроба отримати інформацію про користувача, який спричинив помилку
    user: User | None = None
    if event.update.message:
        user = event.update.message.from_user
    elif event.update.callback_query:
        user = event.update.callback_query.from_user

    user_info = "N/A"
    if user:
        user_info = f"{user.full_name} (@{user.username}, ID: {user.id})"

    # Формування детального повідомлення для адміністратора
    update_details = event.update.model_dump_json(indent=2, exclude_none=True)
    error_message_to_admin = [
        "🚨 <b>Сталася помилка у боті!</b> 🚨",
        "",
        f"👤 <b>Користувач:</b> {hitalic(user_info)}",
        f"📝 <b>Виключення:</b>",
        hcode(f"{type(event.exception).__name__}: {event.exception}"),
        "",
        "🗂 <b>Деталі оновлення (Update):</b>",
        hcode(update_details)
    ]

    try:
        await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text="\n".join(error_message_to_admin)
        )
    except Exception as e:
        logger.error(f"Критична помилка в самому обробнику помилок під час надсилання звіту адміну: {e}", exc_info=True)
