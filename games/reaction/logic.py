"""
Бізнес-логіка для гри на реакцію.
Керує ігровим циклом: очікування, зміна сигналу.
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


class ReactionGameLogic:
    """Керує повним циклом гри на реакцію для одного користувача."""

    def __init__(self, bot: Bot, state: FSMContext, chat_id: int, message_id: int):
        self.bot = bot
        self.state = state
        self.chat_id = chat_id
        self.message_id = message_id

    async def _turn_light_green(self, delay: float):
        """Фонове завдання, яке змінює сигнал на зелений."""
        await asyncio.sleep(delay)
        # Перевіряємо, чи гра ще триває (користувач не зробив фальстарт)
        current_state = await self.state.get_state()
        if current_state != ReactionGameState.in_progress:
            logger.debug(f"Game ({self.message_id}): Canceled, user already clicked (foul start).")
            return

        green_light_time = time.monotonic()
        await self.state.update_data(green_light_time=green_light_time)
        logger.info(f"Game ({self.message_id}): Light is GREEN at {green_light_time}")

        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text="🟢 НАТИСКАЙ!",
                reply_markup=create_reaction_game_keyboard(),
            )
        except TelegramAPIError as e:
            logger.warning(f"Game ({self.message_id}): Could not edit message to GREEN: {e}")

    async def start_game(self):
        """Запускає ігровий цикл з можливістю фальстарту."""
        await self.state.set_state(ReactionGameState.in_progress)
        
        # Негайно показуємо кнопку і червоне світло
        await self.bot.edit_message_text(
            chat_id=self.chat_id,
            message_id=self.message_id,
            text="🔴 Приготуйся...",
            reply_markup=create_reaction_game_keyboard(),
        )
        logger.info(f"Game ({self.message_id}): Red light is ON.")

        # Запускаємо фонове завдання, яке увімкне зелене світло
        delay = random.uniform(2.0, 5.0)
        asyncio.create_task(self._turn_light_green(delay))
