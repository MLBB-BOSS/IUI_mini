"""
Бізнес-логіка для гри на реакцію.
Керує ігровим циклом: анімація, очікування, зміна сигналу.
"""
import asyncio
import random
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

from config import logger
from games.reaction.keyboards import create_reaction_game_keyboard
from games.reaction.states import ReactionGameState

# Константа для розширення ігрового поля
PADDING = "ㅤ" * 12  # Hangul Filler (U+3164)


class ReactionGameLogic:
    """Керує повним циклом гри на реакцію для одного користувача."""

    def __init__(self, bot: Bot, state: FSMContext, chat_id: int, message_id: int):
        self.bot = bot
        self.state = state
        self.chat_id = chat_id
        self.message_id = message_id

    async def _update_message(self, text: str, **kwargs):
        """Безпечно оновлює повідомлення, ігноруючи помилки "not modified"."""
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                **kwargs,
            )
            return True
        except TelegramAPIError as e:
            if "message is not modified" in str(e):
                return True
            logger.warning(f"Game ({self.message_id}): Could not edit message: {e}")
            return False

    async def _animate_and_trigger_green_light(self):
        """
        Фонове завдання, яке показує анімацію червоного світла,
        а потім змінює сигнал на зелений.
        """
        # Фаза 1: Анімація червоного світла
        red_lights = ["🔴", "🔴 🔴", "🔴 🔴 🔴"]
        for i in range(len(red_lights)):
            if await self.state.get_state() != ReactionGameState.in_progress:
                logger.debug(f"Game ({self.message_id}): Canceled during animation.")
                return

            # ❗️ НОВЕ: Форматування з розривами рядків та паддінгом
            text = f"Приготуйся...\n\n{PADDING}\n{red_lights[i]}\n{PADDING}"
            await self._update_message(text, reply_markup=create_reaction_game_keyboard())
            await asyncio.sleep(0.7)

        # Фаза 2: Випадкова затримка
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)

        if await self.state.get_state() != ReactionGameState.in_progress:
            logger.debug(f"Game ({self.message_id}): Canceled before green light.")
            return

        # Фаза 3: Зелене світло
        green_light_time = time.monotonic()
        await self.state.update_data(green_light_time=green_light_time)
        logger.info(f"Game ({self.message_id}): Light is GREEN at {green_light_time}")
        
        # ❗️ НОВЕ: Форматування для зеленого світла
        text = f"🟢 НАТИСКАЙ! 🟢\n\n{PADDING}\n🟢\n{PADDING}"
        await self._update_message(text, reply_markup=create_reaction_game_keyboard())

    async def start_game(self):
        """Запускає ігровий цикл з анімацією та можливістю фальстарту."""
        await self.state.set_state(ReactionGameState.in_progress)

        initial_text = f"Гра починається!\n\n{PADDING}\n...\n{PADDING}"
        await self._update_message(
            initial_text,
            reply_markup=create_reaction_game_keyboard()
        )
        logger.info(f"Game ({self.message_id}): Initial screen is ON.")

        asyncio.create_task(self._animate_and_trigger_green_light())
