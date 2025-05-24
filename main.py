"""
MLBB Expert Bot
===============

Мінімалістична, але високоякісна версія Telegram-бота-асистента для Mobile Legends: Bang Bang,
зосереджена на одній ключовій функції — наданні розумних, структурованих і зручних для
читання відповідей від GPT-4o-mini.

• Python 3.11+
• aiogram 3.19+
• OpenAI Chat Completions API

Author : MLBB-BOSS
Date   : 2025-05-24
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

from aiohttp import ClientSession, ClientTimeout
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

# ---------------------------------------------------------------------------#
#                         НАЛАШТУВАННЯ / CONFIGURATION                       #
# ---------------------------------------------------------------------------#
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("MLBBExpertBot")

load_dotenv()

TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌  Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

# ---------------------------------------------------------------------------#
#                               GPT-АСИСТЕНТ                                 #
# ---------------------------------------------------------------------------#
class MLBBChatGPT:
    """GPT-асистент, що формує промпти й пост-обробляє відповіді для Telegram."""

    _HEADER_EMOJIS: dict[str, str] = {
        "карти": "🗺️",
        "об'єкт": "🛡️",
        "тактик": "⚔️",
        "позиці": "📍",
        "комунікац": "💬",
        "герой": "🦸",
        "фарм": "💰",
        "ротац": "🔄",
        "командн": "🤝",
    }

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None

    # ------------------------------ CONTEXT --------------------------------#
    async def __aenter__(self) -> "MLBBChatGPT":
        self.session = ClientSession(
            timeout=ClientTimeout(total=30),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.session:
            await self.session.close()

    # ------------------------------ PROMPT ---------------------------------#
    @staticmethod
    def _create_smart_prompt(user_name: str) -> str:
        """Формує системний промпт із динамічним привітанням та правилами стилю."""
        hour = datetime.now().hour
        greeting = (
            "Доброго ранку"
            if 5 <= hour < 12
            else "Доброго дня"
            if 12 <= hour < 17
            else "Доброго вечора"
            if 17 <= hour < 22
            else "Доброї ночі"
        )

        return (
            f"🎮 {greeting}, {user_name}! Ти спілкуєшся з експертом Mobile Legends.\n\n"
            "ТВОЯ РОЛЬ: профі-асистент із 5+ роками досвіду гри та коучінгу MLBB.\n\n"
            "✅ ЩО ТИ РОБИШ:\n"
            "• Пояснюєш механіки, стратегії, мету, патчі\n"
            "• Даєш поради щодо героїв та командної взаємодії\n"
            "• Мотивуєш гравців і підтримуєш командний дух\n\n"
            "❌ ЧОГО ТИ НЕ РОБИШ:\n"
            "• Не рекомендуєш точні білди (швидко застарівають)\n"
            "• Не використовуєш HTML або заголовки Markdown (###)\n\n"
            "💬 СТИЛЬ: дружній, енергійний, до 200 слів, з емодзі та чіткими відступами."
        )

    # ---------------------------- BEAUTIFIER -------------------------------#
    def _beautify_response(self, raw_text: str) -> str:
        """Перетворює markdown-розмітку GPT на приємний для Telegram формат."""
        # 1) Заголовки ### / ##  →  емодзі + <b>Title</b>:
        def _hdr(match: re.Match[str]) -> str:
            title = match.group(1).strip(" :").capitalize()
            emoji = next(
                (em for key, em in self._HEADER_EMOJIS.items() if key in title.lower()),
                "🔹",
            )
            return f"\n\n{emoji} <b>{title}</b>:"

        text = re.sub(r"^#{2,3}\s*(.+)$", _hdr, raw_text, flags=re.MULTILINE)

        # 2) Звичайні маркери списку → булет •
        text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

        # 3) Прибрати надмірні пусті рядки
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text

    # ----------------------------- QUERY -----------------------------------#
    async def ask(self, user_name: str, user_query: str) -> str:
        """Відправляє запит до OpenAI та повертає оформлену відповідь."""
        assert self.session, "Session not initialised. Use 'async with'."

        payload = {
            "model": "gpt-4.1",
            "messages": [
                {"role": "system", "content": self._create_smart_prompt(user_name)},
                {"role": "user", "content": user_query},
            ],
            "max_tokens": 500,
            "temperature": 0.8,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2,
        }

        try:
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions", json=payload
            ) as resp:
                if resp.status != 200:
                    logger.error("OpenAI API error: %s", resp.status)
                    return "Вибач, сталася технічна помилка 😔 Спробуй ще раз."

                data = await resp.json()
                raw = data["choices"][0]["message"]["content"]

                # Легка очистка від **bold** / *italic* і HTML, які GPT інколи вставляє
                clean = re.sub(r"<[^>]+>", "", raw)
                clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)
                clean = re.sub(r"\*([^*]+)\*", r"\1", clean)

                return self._beautify_response(clean)

        except Exception as exc:  # noqa: BLE001
            logger.exception("GPT request failed: %s", exc)
            return "Не вдалося отримати відповідь від GPT 😕 Спробуй пізніше."

# ---------------------------------------------------------------------------#
#                                   БОТ                                      #
# ---------------------------------------------------------------------------#
bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# ------------------------------- HANDLERS ----------------------------------#
@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user_name = message.from_user.first_name
    hour = datetime.now().hour
    greeting, emoji = (
        ("Доброго ранку", "🌅")
        if 5 <= hour < 12
        else ("Доброго дня", "☀️")
        if 12 <= hour < 17
        else ("Доброго вечора", "🌆")
        if 17 <= hour < 22
        else ("Доброї ночі", "🌙")
    )

    text = (
        f"{greeting}, <b>{user_name}</b>! {emoji}\n\n"
        "🎮 Ласкаво просимо до <b>MLBB Expert Chat Bot</b>!\n\n"
        "Напиши команду <code>/go</code> та своє запитання.\n\n"
        "<b>Приклади:</b>\n"
        "• <code>/go соло стратегії для швидкого ранк-апу</code>\n"
        "• <code>/go дуо тактики для доміну в лейті</code>\n"
        "• <code>/go як читати карту та контролювати об'єкти</code>\n\n"
        "Готовий допомогти тобі підкорити Land of Dawn! 🚀"
    )
    await message.answer(text)
    logger.info("Sent welcome to %s", user_name)


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    user_name = message.from_user.first_name
    query = message.text.replace("/go", "", 1).strip()

    if not query:
        await message.reply(
            "📝 Спершу додай запит після /go.\n\n"
            "<b>Приклади:</b>\n"
            "• /go соло стратегії для швидкого ранк-апу\n"
            "• /go тріо комбо для командних боїв"
        )
        return

    thinking_msgs = [
        f"🤔 {user_name}, думаю над твоїм питанням...",
        f"🧠 Аналізую запит, {user_name}!",
        f"⚡ Готую експертну відповідь...",
        f"🎯 Шукаю найкращі поради, {user_name}!",
    ]
    temp_msg = await message.reply(thinking_msgs[hash(query) % len(thinking_msgs)])

    start = time.time()
    async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
        reply = await gpt.ask(user_name, query)
    elapsed = time.time() - start

    admin_note = f"\n\n<i>⏱ {elapsed:.2f}s</i>" if message.from_user.id == ADMIN_USER_ID else ""
    try:
        await temp_msg.edit_text(reply + admin_note)
    except TelegramAPIError:
        await message.reply(reply)

    logger.info("Answered %s in %.2fs", user_name, elapsed)


# ---------------------------- ERROR HANDLER --------------------------------#
@dp.errors()
async def on_error(event, exc):
    logger.error("Handler error: %s", exc, exc_info=True)
    if hasattr(event, "message") and event.message:
        user = event.message.from_user.first_name if event.message.from_user else "друже"
        await event.message.answer(
            f"Вибач, {user}, сталася помилка 😔\nСпробуй ще раз пізніше."
        )


# -------------------------------- LAUNCH -----------------------------------#
async def main() -> None:
    logger.info("🚀  Запускаю MLBB Expert Bot...")
    try:
        me = await bot.get_me()
        logger.info("Bot @%s is up", me.username)

        if ADMIN_USER_ID:
            try:
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB Expert Bot запущено!</b>\n@{me.username}",
                )
            except Exception:  # noqa: BLE001
                pass

        await dp.start_polling(bot)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown requested by user")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

