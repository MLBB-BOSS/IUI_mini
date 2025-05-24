"""
MLBB Expert Bot - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.

Python 3.11+ | aiogram 3.19+ | OpenAI GPT-4o-mini
Author: MLBB-BOSS | Date: 2025-05-24
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

# === НАЛАШТУВАННЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

# === РОЗУМНИЙ GPT АСИСТЕНТ ===
class MLBBChatGPT:
    """Спеціалізований GPT асистент для MLBB з персоналізацією."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None

    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=30),
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """Створює розумний промпт для якісних відповідей."""
        current_hour = datetime.now().hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
                  "Доброго дня" if 12 <= current_hour < 17 else \
                  "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

        return f"""
🎮 {greeting}, {user_name}! Ти в MLBB чаті та спілкуєшся з експертом Mobile Legends!

ТВОЯ РОЛЬ: Експертний асистент Mobile Legends Bang Bang з 5+ роками досвіду.

✅ ЩО ТИ РОБИШ:
• Пояснюєш механіки та стратегії MLBB
• Допомагаєш з вибором героїв та ролей
• Даєш поради про тактики та командну гру
• Розповідаєш про мету, патчі та зміни в грі
• Пояснюєш ігрові терміни простими словами
• Мотивуєш та підтримуєш геймерський дух

❌ ЧОГО ТИ НЕ РОБИШ:
• НЕ даєш конкретні білди предметів (можуть бути застарілими)
• НЕ рекомендуєш точні артефакти або емблеми
• НЕ використовуєш HTML теги або складне форматування

💬 СТИЛЬ СПІЛКУВАННЯ:
- Звертайся до {user_name} на ім'я
- Використовуй емодзі для кращого сприйняття
- Будь ентузіастичним та дружнім
- Говори як досвідчений тіммейт
- Максимум 200 слів на відповідь
- Структуруй відповіді чітко та зрозуміло

Готовий допомогти {user_name} стати кращим в MLBB! 🚀
"""

    async def get_response(self, user_name: str, user_query: str) -> str:
        """Отримує якісну відповідь від GPT."""
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 500,
            "temperature": 0.8,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2
        }

        try:
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                if response.status != 200:
                    logger.error(f"OpenAI API помилка: {response.status}")
                    return f"Вибач, {user_name}, технічні проблеми 😔 Спробуй ще раз!"

                result = await response.json()
                gpt_text = result["choices"][0]["message"]["content"]

                # Очищення від небажаних елементів
                clean_text = re.sub(r"<[^>]*>", "", gpt_text)  # HTML теги
                clean_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean_text)  # markdown
                clean_text = re.sub(r"\*([^*]+)\*", r"\1", clean_text)

                return clean_text.strip()

        except Exception as e:
            logger.exception(f"GPT помилка: {e}")
            return f"Не зміг обробити запит, {user_name} 😕 Спробуй пізніше!"

# === БОТ ===
bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Просте та ефективне привітання."""
    user_name = message.from_user.first_name
    current_hour = datetime.now().hour

    if 5 <= current_hour < 12:
        greeting = "Доброго ранку"
        emoji = "🌅"
    elif 12 <= current_hour < 17:
        greeting = "Доброго дня"
        emoji = "☀️"
    elif 17 <= current_hour < 22:
        greeting = "Доброго вечора"
        emoji = "🌆"
    else:
        greeting = "Доброї ночі"
        emoji = "🌙"

    welcome_text = f"""
{greeting}, <b>{user_name}</b>! {emoji}

🎮 Вітаю в MLBB Expert Chat Bot!

Я - твій персональний експерт по Mobile Legends Bang Bang, готовий допомогти з будь-якими питаннями про гру!

<b>💡 Як користуватися:</b>
Просто напиши своє питання після команди /go

<b>🚀 Приклади стратегічних запитів:</b>
• <code>/go соло стратегії для швидкого ранк-апу</code>
• <code>/go дуо тактики для доміну в лейті</code>
• <code>/go тріо комбо для командних боїв</code>
• <code>/go як читати карту та контролювати об'єкти</code>

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    await message.answer(welcome_text)
    logger.info(f"✅ Привітання для {user_name}")

@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """Головна функція - якісне спілкування через GPT."""
    user_name = message.from_user.first_name
    user_query = message.text.replace("/go", "", 1).strip()

    if not user_query:
        await message.reply(
            f"Привіт, <b>{user_name}</b>! 👋\n\n"
            "Напиши своє питання після /go\n"
            "<b>Приклади:</b>\n"
            "• /go соло стратегії для швидкого ранк-апу\n"
            "• /go дуо тактики для доміну в лейті\n"
            "• /go тріо комбо для командних боїв\n"
            "• /go як читати карту та контролювати об'єкти"
        )
        return

    thinking_messages = [
        f"🤔 {user_name}, думаю над твоїм питанням...",
        f"🧠 Аналізую запит, {user_name}!",
        f"⚡ Готую експертну відповідь для тебе!",
        f"🎯 {user_name}, шукаю найкращі поради!"
    ]

    thinking_msg = await message.reply(
        thinking_messages[hash(user_query) % len(thinking_messages)]
    )

    start_time = time.time()

    # Отримуємо відповідь від GPT
    async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
        response = await gpt.get_response(user_name, user_query)

    processing_time = time.time() - start_time

    # Додаємо інфо для адміна
    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с</i>"

    try:
        await thinking_msg.edit_text(f"{response}{admin_info}")
        logger.info(f"📤 Відповідь для {user_name} ({processing_time:.2f}s)")
    except TelegramAPIError:
        await message.reply(response)

# Обробка помилок
@dp.errors()
async def error_handler(event, exception):
    logger.error(f"🚨 Помилка: {exception}", exc_info=True)

    if hasattr(event, 'message') and event.message:
        user_name = event.message.from_user.first_name if event.message.from_user else "друже"
        await event.message.answer(
            f"Вибач, {user_name}, сталася помилка 😔\n"
            "Спробуй ще раз через хвилину!"
        )

# === ЗАПУСК ===
async def main() -> None:
    """Запуск бота."""
    logger.info("🚀 Запуск MLBB Expert Bot...")

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} готовий!")

        # Сповіщення адміна
        if ADMIN_USER_ID:
            try:
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB Expert Bot запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {datetime.now().strftime('%H:%M:%S')}\n"
                    f"🟢 Готовий до роботи!"
                )
            except Exception:
                pass

        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено")
    except Exception as e:
        logger.critical(f"💥 Критична помилка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
