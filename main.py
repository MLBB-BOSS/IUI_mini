"""
main.py
Мінімальна асинхронна версія Telegram-бота для MLBB-спільноти на основі aiogram 3.19+ та Python 3.11+.
Додає інтеграцію GPT-4 Vision для аналізу скріншотів по команді /vision.

Рекомендації:
- Для роботи потрібні TELEGRAM_BOT_TOKEN і OPENAI_API_KEY у конфігурації (Heroku Config Vars або .env).
- Працює тільки з зображеннями (фото/скріншоти) до 10 МБ.
- Відповідь GPT завжди повертається текстом без HTML.
"""

import asyncio
import logging
import os
from typing import Any

from aiogram import Bot, Dispatcher, Router
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

TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не встановлено! Бот не зможе запуститися.")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required in environment variables.")

if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY не встановлено! Vision-функціонал буде недоступний.")
    raise RuntimeError("OPENAI_API_KEY is required in environment variables.")

__all__ = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"]

bot: Bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp: Dispatcher = Dispatcher()
router: Router = Router()


# =======================
# Vision аналіз зображень
# =======================
async def analyze_image_with_vision(image_bytes: bytes) -> str:
    """
    Надсилає зображення до GPT-4 Vision (OpenAI API) і повертає аналіз.
    :param image_bytes: Байт-контент зображення.
    :return: Текст аналізу або повідомлення про помилку.
    """
    import base64
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/jpeg;base64,{image_base64}"

    vision_prompt = (
        "Це скріншот з ігрового акаунта Mobile Legends: Bang Bang.\n"
        "Опиши, що саме на ньому зображено, які основні ігрові дані видно, "
        "та дай коротку пораду гравцю. Відповідай українською мовою."
    )
    messages = [
        {
            "role": "system",
            "content": "Ти — аналітик ігрових скріншотів Mobile Legends."
        },
        {
            "role": "user",
            "content": f"{vision_prompt}\n\nЗображення (base64):\n{data_uri}"
        },
    ]
    payload = {
        "model": "gpt-4-vision-preview",
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with ClientSession() as session:
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=40
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Vision API error: {response.status} - {error_text}")
                    return "❌ Не вдалося отримати аналіз скріншота. Спробуйте ще раз."
                result = await response.json()
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.exception(f"Помилка аналізу скріншота: {e}")
            return "❌ Сталася помилка під час аналізу скріншота."


# ===========================
# Обробник команди /vision
# ===========================
@router.message(Command("vision"))
async def cmd_vision_instruct(message: Message) -> None:
    """
    Інструктує користувача надіслати скріншот для аналізу.
    """
    await message.reply(
        "📸 Надішліть скріншот профілю, статистики або матчу MLBB як фото у відповідь на це повідомлення.\n"
        "Бот проаналізує його за допомогою GPT-4 Vision та поверне результат.",
        reply_to_message_id=message.message_id,
        parse_mode=None
    )


# ===============================
# Обробка отриманих скріншотів
# ===============================
@router.message(
    lambda m: m.reply_to_message and m.reply_to_message.text and "/vision" in m.reply_to_message.text,
    lambda m: m.photo
)
async def handle_vision_screenshot(message: Message) -> None:
    """
    Приймає скріншот у відповідь на /vision, аналізує його через GPT-4 Vision і повертає результат.
    :param message: Об'єкт повідомлення з фотографією.
    """
    photo = message.photo[-1]  # Найякісніше зображення
    try:
        file = await bot.get_file(photo.file_id)
        image_bytes_io = await bot.download_file(file.file_path)
        image_bytes = await image_bytes_io.read()
        if len(image_bytes) > 10 * 1024 * 1024:
            await message.reply("❌ Зображення занадто велике (максимум 10 МБ).")
            return

        await message.reply("⏳ Виконується аналіз скріншота... Це може зайняти до 30 секунд.", parse_mode=None)

        vision_result = await analyze_image_with_vision(image_bytes)
        await message.reply(vision_result, parse_mode=None)

    except Exception as exc:
        logger.exception(f"Помилка під час обробки скріншота: {exc}")
        await message.reply("❌ Сталася помилка під час обробки скріншота.", parse_mode=None)


# =========================
# Глобальний error handler
# =========================
@dp.errors()
async def global_error_handler(event: Any, exception: Exception) -> Any:
    """
    Глобальний обробник винятків. Логує помилки та інформує розробника.
    :param event: Подія, що спричинила помилку.
    :param exception: Виняток, що виник.
    """
    logger.error(f"Виникла помилка: {exception}", exc_info=True)
    # За потреби можна додати сповіщення адміну


# =========================
# Запуск бота
# =========================
async def main() -> None:
    """
    Основний цикл запуску бота.
    """
    logger.info("Бот запускається...")
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    except Exception as exc:
        logger.critical(f"Фатальна помилка під час запуску polling: {exc}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинено вручну (KeyboardInterrupt/SystemExit)")
