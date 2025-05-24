"""
main.py
Мінімальна асинхронна робоча версія Telegram-бота для MLBB-спільноти на основі aiogram 3.19+ та Python 3.11+.
Створено з урахуванням світових стандартів якості, типізації, PEP 8, докладних docstrings і коректної обробки помилок.
"""

import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from typing import Any

# --- Налаштування логування ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s"
)
logger = logging.getLogger(__name__)

# --- Отримання токена ---
TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не встановлено! Бот не зможе запуститися.")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required in environment variables.")

__all__ = ["TELEGRAM_BOT_TOKEN"]

# --- Ініціалізація бота та диспетчера ---
bot: Bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp: Dispatcher = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """
    Відповідає на команду /start.
    :param message: Об'єкт повідомлення від користувача.
    """
    await message.answer(
        "Вітаю! 🤖 Бот успішно запущено.\n"
        "Це мінімальна асинхронна версія для MLBB-спільноти.\n\n"
        "Спробуйте додати нові команди — інфраструктура вже готова!"
    )


@dp.errors()
async def global_error_handler(update: Any, exception: Exception) -> None:
    """
    Глобальний обробник винятків. Логує помилки та інформує розробника.
    :param update: Оновлення, що спричинило помилку.
    :param exception: Виняток, що виник.
    """
    logger.error(f"Виникла помилка: {exception}", exc_info=True)
    # Можна додати логіку сповіщення адміністратора або відправки повідомлення в чат


async def main() -> None:
    """
    Основний цикл запуску бота.
    """
    logger.info("Бот запускається...")
    try:
        await dp.start_polling(bot)
    except Exception as exc:
        logger.critical(f"Фатальна помилка під час запуску polling: {exc}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинено вручну (KeyboardInterrupt/SystemExit)")
