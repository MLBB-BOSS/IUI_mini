"""
main.py
Мінімальна асинхронна робоча версія Telegram-бота для MLBB-спільноти на основі aiogram 3.19+ та Python 3.11+.
Додано інтеграцію GPT для обробки запитів через команду /go.
"""

import asyncio
import logging
import os
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiohttp import ClientSession
from dotenv import load_dotenv

# --- Налаштування логування ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s"
)
logger = logging.getLogger(__name__)

# --- Завантаження змінних середовища ---
load_dotenv()

# --- Отримання токенів ---
TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не встановлено! Бот не зможе запуститися.")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required in environment variables.")

if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY не встановлено! GPT-функціонал буде недоступний.")
    raise RuntimeError("OPENAI_API_KEY is required in environment variables.")

__all__ = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"]

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
        "Спробуйте команду /go <ваш запит>, щоб отримати відповідь від GPT!"
    )


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """
    Обробляє команду /go, надсилає запит до GPT-4 і повертає відповідь.
    :param message: Об'єкт повідомлення від користувача.
    """
    user_query = message.text.replace("/go", "").strip()

    if not user_query:
        await message.reply("⚠️ Будь ласка, введіть запит після команди /go.")
        return

    await message.reply("⏳ GPT обробляє ваш запит, зачекайте...")

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    payload = {
        "model": "gpt-4",
        "messages": [
            {"role": "system", "content": "Ви - асистент для Mobile Legends Bang Bang."},
            {"role": "user", "content": user_query}
        ],
        "max_tokens": 200,
        "temperature": 0.7
    }

    # Відправка запиту до OpenAI
    async with ClientSession() as session:
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers=headers
            ) as response:
                if response.status != 200:
                    logger.error(f"Помилка API OpenAI: {response.status}")
                    await message.reply("❌ Не вдалося отримати відповідь від GPT.")
                    return

                result = await response.json()
                gpt_response = result["choices"][0]["message"]["content"]
                await message.reply(f"🤖 GPT відповідає:\n\n{gpt_response}")

        except Exception as e:
            logger.exception(f"Помилка виклику OpenAI API: {e}")
            await message.reply("❌ Сталася помилка при спробі отримати відповідь від GPT.")


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
