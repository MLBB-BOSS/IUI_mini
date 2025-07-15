"""
Обробники для гри на реакцію.

Виконують роль "контролера", приймаючи вхідні дані від користувача
та делегуючи виконання бізнес-логіки сервісному класу ReactionGameLogic.
"""
import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import logger
from games.reaction.logic import ReactionGameLogic
from games.reaction.states import ReactionGameState
# TODO: Створити та імпортувати функцію збереження результату
# from .crud import save_reaction_score

reaction_router = Router(name="reaction_game")


@reaction_router.message(Command("reaction", prefix="!/"))
async def start_reaction_game_handler(message: Message, bot: Bot, state: FSMContext):
    """
    Обробник команди /reaction. Запускає гру для користувача.
    """
    if not message.from_user:
        return

    # Перевіряємо, чи користувач вже не в грі, щоб уникнути конфліктів
    current_state = await state.get_state()
    if current_state is not None:
        await message.reply(
            "Ви вже перебуваєте в активній дії. Завершіть її або використайте /cancel."
        )
        return

    try:
        # 1. Відправляємо початкове повідомлення-заглушку
        game_message = await message.answer("🚦 Гра на реакцію починається...")
        
        # 2. Ініціалізуємо логіку гри
        game = ReactionGameLogic(
            bot=bot,
            state=state,
            chat_id=game_message.chat.id,
            message_id=game_message.message_id,
        )
        
        # 3. Запускаємо ігровий цикл у фоновому завданні, щоб не блокувати бота
        asyncio.create_task(game.start_game())
        logger.info(
            f"User {message.from_user.id} started a reaction game. "
            f"Message ID: {game_message.message_id}"
        )

    except TelegramAPIError as e:
        logger.error(f"Failed to send initial game message for user {message.from_user.id}: {e}")
        await message.reply("Не вдалося почати гру через помилку Telegram. Спробуйте ще раз.")
    except Exception as e:
        logger.error(f"Unexpected error on game start for user {message.from_user.id}: {e}", exc_info=True)
        await message.reply("Сталася невідома помилка при запуску гри.")


@reaction_router.callback_query(
    F.data == "reaction_game:stop",
    StateFilter(ReactionGameState.in_progress)
)
async def stop_reaction_game_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Обробляє натискання кнопки "СТОП", фіксує час та показує результат.
    """
    user_id = callback.from_user.id
    end_time = time.monotonic()
    
    data = await state.get_data()
    start_time = data.get("start_time")
    game_message_id = data.get("game_message_id")

    # Перевірка, чи всі дані на місці
    if not all([start_time, game_message_id]):
        logger.warning(f"User {user_id} pressed stop, but state data is missing.")
        await callback.answer("Помилка: дані гри втрачено. Спробуйте почати знову.", show_alert=True)
        await state.clear()
        return

    await state.clear()
    
    reaction_time_sec = end_time - start_time
    reaction_time_ms = int(reaction_time_sec * 1000)

    # Базовий анти-чит
    if reaction_time_ms < 100:
        result_text = (
            f"⏱️ Час: {reaction_time_ms} мс\n\n"
            "🤔 Фальстарт! Схоже, ти натиснув ще до зеленого світла. "
            "Спробуй ще раз!"
        )
    else:
        # TODO: Інтегрувати збереження результату в БД
        # await save_reaction_score(user_id, reaction_time_ms)
        result_text = (
            f"🚀 Твій результат: <b>{reaction_time_ms} мс</b>!\n\n"
            "Чудова реакція! Спробуєш побити свій рекорд?"
        )

    try:
        await bot.edit_message_text(
            text=result_text,
            chat_id=callback.message.chat.id,
            message_id=game_message_id,
            reply_markup=None, # Видаляємо кнопку після гри
        )
        await callback.answer(f"Ваш час: {reaction_time_ms} мс", show_alert=False)
    except TelegramAPIError as e:
        # Помилка може виникнути, якщо повідомлення було видалено
        logger.warning(f"Could not edit game message {game_message_id} after completion: {e}")
        await callback.answer(f"Ваш час: {reaction_time_ms} мс. Не вдалося оновити повідомлення.", show_alert=True)


def register_reaction_handlers(dp):
    """Реєструє обробники гри в головному диспетчері."""
    dp.include_router(reaction_router)
    logger.info("✅ Обробники для гри 'Reaction Time' зареєстровано.")
