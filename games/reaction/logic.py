"""
Сервісний шар для гри на реакцію.

Інкапсулює всю бізнес-логіку гри: анімацію, керування станом,
вимірювання часу та взаємодію з FSM.
"""
import asyncio
import random
import time
from typing import final

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

from config import logger
from games.reaction.keyboards import create_reaction_game_keyboard
from games.reaction.states import ReactionGameState

# Константи для візуалізації гри
LIGHTS_OFF = "⚫️"
LIGHTS_RED = "🔴"
LIGHTS_GREEN = "🟢"
SEPARATOR = " "

@final
class ReactionGameLogic:
    """
    Керує повним ігровим циклом гри на реакцію "Світлофор".
    """

    def __init__(self, bot: Bot, state: FSMContext, chat_id: int, message_id: int):
        self._bot = bot
        self._state = state
        self._chat_id = chat_id
        self._message_id = message_id

    async def start_game(self) -> None:
        """
        Запускає ігровий цикл: анімація "світлофора" та встановлення стартового часу.
        """
        try:
            # Фаза 1: Анімація червоних вогнів
            await self._run_countdown_animation()

            # Фаза 2: Випадкова затримка перед стартом
            # Це ключовий елемент для запобігання шахрайству
            final_delay = random.uniform(0.7, 2.5)
            logger.debug(f"Game ({self._message_id}): Final delay before green light is {final_delay:.2f}s")
            await asyncio.sleep(final_delay)

            # Фаза 3: Зелене світло та старт
            await self._show_green_light_and_start_timer()

        except TelegramAPIError as e:
            logger.error(
                f"Game ({self._message_id}): Telegram API error during game start sequence: {e}",
                exc_info=True
            )
            await self._cleanup_on_error("Помилка під час запуску гри. Спробуйте ще раз.")
        except Exception as e:
            logger.error(
                f"Game ({self._message_id}): Unexpected error in start_game: {e}",
                exc_info=True
            )
            await self._cleanup_on_error("Невідома помилка. Гра скасована.")

    async def _run_countdown_animation(self) -> None:
        """
        Виконує анімацію "запалювання" червоних вогнів.
        """
        total_lights = 5
        for i in range(1, total_lights + 1):
            delay = random.uniform(0.5, 1.2)
            await asyncio.sleep(delay)

            lights_on = LIGHTS_RED * i
            lights_off = LIGHTS_OFF * (total_lights - i)
            text = f"Приготуйся...!\n\n{SEPARATOR.join(list(lights_on + lights_off))}"
            
            await self._bot.edit_message_text(
                text=text,
                chat_id=self._chat_id,
                message_id=self._message_id
            )

    async def _show_green_light_and_start_timer(self) -> None:
        """
        Відображає зелене світло, встановлює стан та зберігає час старту.
        """
        green_lights = SEPARATOR.join([LIGHTS_GREEN] * 5)
        text = f"СТАРТ!\n\n{green_lights}"

        await self._bot.edit_message_text(
            text=text,
            chat_id=self._chat_id,
            message_id=self._message_id,
            reply_markup=create_reaction_game_keyboard()
        )
        
        # Встановлюємо стан та фіксуємо точний час старту
        start_time = time.monotonic()
        await self._state.set_state(ReactionGameState.in_progress)
        await self._state.update_data(start_time=start_time, game_message_id=self._message_id)
        logger.info(f"Game ({self._message_id}): Timer started at {start_time}")

    async def _cleanup_on_error(self, error_text: str) -> None:
        """
        Безпечно завершує гру у випадку помилки.
        """
        try:
            await self._bot.edit_message_text(
                text=error_text,
                chat_id=self._chat_id,
                message_id=self._message_id,
                reply_markup=None
            )
        except TelegramAPIError:
            logger.warning(f"Game ({self._message_id}): Could not edit message during cleanup.")
        finally:
            await self._state.clear()
