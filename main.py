"""
MLBB Expert Bot - Мінімалістична версія з максимальною якістю GPT-спілкування.
Фокус на одній функції: структуровані розумні відповіді про Mobile Legends Bang Bang.

Python 3.11+ | aiogram 3.19+ | OpenAI GPT-4o-mini
Author: MLBB-BOSS
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
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
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

# === GPT-АСИСТЕНТ ДЛЯ MLBB ===

class MLBBChatGPT:
    """
    Спеціалізований GPT-асистент для MLBB з персоналізацією та структурованістю.
    """

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

    def _create_structured_prompt(self, user_name: str, user_query: str) -> str:
        """
        Створює промпт для GPT з вимогою структурованої відповіді.
        """
        current_hour = datetime.now().hour
        if 5 <= current_hour < 12:
            greeting = "Доброго ранку"
        elif 12 <= current_hour < 17:
            greeting = "Доброго дня"
        elif 17 <= current_hour < 22:
            greeting = "Доброго вечора"
        else:
            greeting = "Доброї ночі"

        # Промпт: структурованість, списки, короткі пункти, уникай стенографії
        return (
            f"{greeting}, {user_name}! Ти спілкуєшся з експертом Mobile Legends Bang Bang для MLBB-спільноти.\n\n"
            "ТВОЯ РОЛЬ:\n"
            "- Експертний коуч MLBB, який пояснює складні речі просто.\n"
            "- Відповідай структуровано, кожен пункт — з нового рядка, із номером, маркером або підзаголовком.\n"
            "- Використовуй короткі абзаци (2-3 речення).\n"
            "- Для багаторівневих порад - роби внутрішні списки.\n"
            "- Не використовуй HTML/Markdown, не згадуй дати патчів і мету.\n"
            "- Не давай білди (предмети, емблеми): тільки стратегії, тактики, командні та індивідуальні поради.\n"
            "- Спочатку обов'язково коротко привітайся із {user_name} по імені.\n"
            "- Відповідь має бути дуже структурованою і легко читаною у Telegram.\n"
            "- Приклад структури:\n"
            "Привіт, ім'я! Ось кілька порад:\n"
            "1. Назва поради\n"
            "   - коротко розкрий суть\n"
            "2. Назва поради\n"
            "   - коротко розкрий суть\n"
            "...\n"
            f"Питання користувача: {user_query}"
        )

    def _postprocess_response(self, text: str) -> str:
        """
        Додатково структурує відповідь GPT для ідеального вигляду у Telegram.
        """
        # Прибрати HTML, markdown, зайві пробіли
        text = re.sub(r"<[^>]*>", "", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"#{1,6}\s*([^\n]+)", r"\1", text)
        # Прибрати згадки про патчі, дати, мету, білди
        text = re.sub(r"(патч|версі[яії]|мет[ааи]|оновлен[яі]|build|білд)[^\n]*\d+", "", text, flags=re.IGNORECASE)
        # Максимум 2 нові рядки поспіль
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Вирівняти маркери
        text = re.sub(r"- ", "• ", text)
        # Вирівняти багаторівневі списки
        text = re.sub(r"\n\s*([0-9]+\.)", r"\n\n\1", text)
        text = re.sub(r"\n\s*•", r"\n•", text)
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Отримує якісну структуровану відповідь від GPT.
        """
        system_prompt = self._create_structured_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 350,
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
                    return f"Вибач, {user_name}, виникли технічні проблеми 😔 Спробуй ще раз!"
                result = await response.json()
                gpt_text = result["choices"][0]["message"]["content"]
                return self._postprocess_response(gpt_text)
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
    """
    Привітання з ідеальним форматуванням, структурою та персоналізацією.
    """
    user_name = message.from_user.first_name
    current_hour = datetime.now().hour

    if 5 <= current_hour < 12:
        greeting, emoji = "Доброго ранку", "🌅"
    elif 12 <= current_hour < 17:
        greeting, emoji = "Доброго дня", "☀️"
    elif 17 <= current_hour < 22:
        greeting, emoji = "Доброго вечора", "🌆"
    else:
        greeting, emoji = "Доброї ночі", "🌙"

    welcome_text = (
        f"{greeting}, <b>{user_name}</b>! {emoji}\n\n"
        f"🎮 <b>Вітаю в MLBB IUI mini!</b>\n\n"
        f"Я — твій персональний про-коуч по Mobile Legends Bang Bang, готовий прокачати твої навички до рівня кіберспортсмена! 🏆\n\n"
        f"💡 <b>Як користуватися:</b>\n"
        f"Просто напиши своє питання після команди <b>/go</b>\n\n"
        f"🚀 <b>Приклади стратегічних запитів:</b>\n"
        f"• /go соло стратегії для швидкого ранк-апу\n"
        f"• /go дуо тактики для доміну в лейті\n"
        f"• /go тріо комбо для командних боїв\n"
        f"• /go як читати карту та контролювати об'єкти\n\n"
        f"🎯 <b>Мої суперсили:</b>\n"
        f"• Розробляю персональні стратегії\n"
        f"• Аналізую твій геймплей\n"
        f"• Навчаю читати противника\n"
        f"• Прокачую твою ментальність\n\n"
        f"Готовий перетворити тебе на справжнього MLBB про-гравця! 💪✨"
    )
    await message.answer(welcome_text)
    logger.info(f"✅ Привітання для {user_name}")

@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """
    Головна функція: структуроване якісне спілкування через GPT.
    """
    user_name = message.from_user.first_name
    user_query = message.text.replace("/go", "", 1).strip()

    if not user_query:
        help_text = (
            f"Привіт, <b>{user_name}</b>! 👋\n\n"
            "Напиши своє питання після /go\n\n"
            "<b>Приклади:</b>\n"
            "• /go соло стратегії для швидкого ранк-апу\n"
            "• /go дуо тактики для доміну в лейті\n"
            "• /go тріо комбо для командних боїв\n"
            "• /go як читати карту та контролювати об'єкти"
        )
        await message.reply(help_text)
        return

    thinking_messages = [
        f"🤔 {user_name}, аналітика йде...",
        f"🧠 Готую структуровану відповідь, {user_name}!",
        f"⚡ {user_name}, формую експертну пораду...",
        f"🎯 {user_name}, розробляю стратегію для тебе!"
    ]
    thinking_msg = await message.reply(thinking_messages[hash(user_query) % len(thinking_messages)])
    start_time = time.time()

    async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
        response = await gpt.get_response(user_name, user_query)

    processing_time = time.time() - start_time
    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с</i>"

    try:
        await thinking_msg.edit_text(f"{response}{admin_info}")
        logger.info(f"📤 Відповідь для {user_name} ({processing_time:.2f}s)")
    except TelegramAPIError:
        await message.reply(response)

@dp.errors()
async def error_handler(event, exception):
    logger.error(f"🚨 Помилка: {exception}", exc_info=True)
    if hasattr(event, 'message') and event.message:
        user_name = event.message.from_user.first_name if event.message.from_user else "друже"
        await event.message.answer(
            f"Вибач, {user_name}, сталася помилка 😔\n"
            "Спробуй ще раз через хвилину!"
        )

async def main() -> None:
    """
    Запуск бота з коректним закриттям сесії.
    """
    logger.info("🚀 Запуск MLBB Expert Bot...")
    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} готовий!")
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
