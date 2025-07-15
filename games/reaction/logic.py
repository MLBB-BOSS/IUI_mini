"""
Бізнес-логіка для гри на реакцію.
Керує ігровим циклом: просунута анімація, очікування, зміна сигналу.
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

PADDING = "ㅤ" * 12

class ReactionGameLogic:
    def __init__(self, bot: Bot, state: FSMContext, chat_id: int, message_id: int):
        self.bot = bot
        self.state = state
        self.chat_id = chat_id
        self.message_id = message_id

    async def _update_message(self, text: str, **kwargs):
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id, message_id=self.message_id, text=text, **kwargs
            )
            return True
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                logger.warning(f"Game ({self.message_id}): Could not edit message: {e}")
            return False

    async def _animate_and_trigger_green_light(self):
        """
        Фонове завдання, що реалізує просунуту анімацію
        з гарантовано безпечними затримками та покращеним ігровим циклом.
        """
        slots = ["⚪️"] * 6
        
        # ❗️ НОВА ЛОГІКА: Заповнюємо лише 5 індикаторів
        for i in range(len(slots) - 1): # Цикл до 5-го елемента (індекс 4)
            if await self.state.get_state() != ReactionGameState.in_progress:
                logger.debug(f"Game ({self.message_id}): Canceled during animation.")
                return
            
            slots[i] = "🔴"
            text = f"Приготуйся...\n\n{PADDING}\n{' '.join(slots)}\n{PADDING}"
            await self._update_message(text, reply_markup=create_reaction_game_keyboard())
            
            # ❗️ НОВА ЛОГІКА: Гарантовано безпечна затримка
            await asyncio.sleep(random.uniform(0.8, 1.5))

        # Фінальна випадкова затримка після заповнення 5 індикаторів
        await asyncio.sleep(random.uniform(0.5, 2.0))
        
        if await self.state.get_state() != ReactionGameState.in_progress:
            return

        # ❗️ НОВА ЛОГІКА: Зелене світло з'являється замість 6-го червоного
        green_light_time = time.monotonic()
        await self.state.update_data(green_light_time=green_light_time)
        logger.info(f"Game ({self.message_id}): Light is GREEN at {green_light_time}")
        
        green_slots = " ".join(["🟢"] * 6)
        text = f"🟢 НАТИСКАЙ! 🟢\n\n{PADDING}\n{green_slots}\n{PADDING}"
        await self._update_message(text, reply_markup=create_reaction_game_keyboard())

    async def start_game(self):
        await self.state.set_state(ReactionGameState.in_progress)
        initial_text = f"Гра починається!\n\n{PADDING}\n{' '.join(['⚪️'] * 6)}\n{PADDING}"
        await self._update_message(
            initial_text, reply_markup=create_reaction_game_keyboard()
        )
        asyncio.create_task(self._animate_and_trigger_green_light())
