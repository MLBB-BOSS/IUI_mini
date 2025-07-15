"""
Обробники для гри на реакцію.
Реалізує логіку ігрового лобі, запуску гри та перегляду лідерів.
"""
import asyncio
import html
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import logger
from games.reaction.crud import get_leaderboard, save_reaction_score
from games.reaction.facts import get_fact_for_time  # ❗️ НОВИЙ ІМПОРТ
from games.reaction.keyboards import (
    create_leaderboard_view_keyboard,
    create_reaction_lobby_keyboard,
)
from games.reaction.logic import ReactionGameLogic
from games.reaction.messages import LOBBY_MESSAGE_TEXT
from games.reaction.states import ReactionGameState

reaction_router = Router(name="reaction_game")

# ... (код лобі, старту, виходу, таблиці лідерів залишається без змін) ...
async def show_lobby(message: Message, state: FSMContext):
    """Відображає ігрове лобі."""
    await state.set_state(ReactionGameState.menu)
    sent_message = await message.answer(
        text=LOBBY_MESSAGE_TEXT,
        reply_markup=create_reaction_lobby_keyboard(),
    )
    await state.update_data(lobby_message_id=sent_message.message_id)


@reaction_router.message(Command("reaction"))
async def reaction_command_handler(message: Message, state: FSMContext):
    """Обробляє команду /reaction, показуючи лобі."""
    await show_lobby(message, state)


@reaction_router.callback_query(
    F.data == "reaction_game:show_lobby", StateFilter(ReactionGameState.menu)
)
async def show_lobby_callback_handler(callback: CallbackQuery, state: FSMContext):
    """Повертає користувача до головного меню гри з таблиці лідерів."""
    if not callback.message:
        return
    await callback.message.edit_text(
        text=LOBBY_MESSAGE_TEXT,
        reply_markup=create_reaction_lobby_keyboard(),
    )
    await callback.answer()

@reaction_router.callback_query(
    F.data == "reaction_game:start", StateFilter(ReactionGameState.menu)
)
async def start_game_callback_handler(callback: CallbackQuery, bot: Bot, state: FSMContext):
    """Запускає гру з меню."""
    if not callback.message:
        return
    try:
        game = ReactionGameLogic(
            bot=bot,
            state=state,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
        asyncio.create_task(game.start_game())
        await callback.answer("Гра починається!")
    except Exception as e:
        logger.error(f"Error starting reaction game from callback: {e}", exc_info=True)
        await callback.answer("Не вдалося почати гру.", show_alert=True)


@reaction_router.callback_query(
    F.data == "reaction_game:exit", StateFilter(ReactionGameState.menu)
)
async def exit_lobby_handler(callback: CallbackQuery, state: FSMContext):
    """Обробляє вихід з ігрового лобі."""
    if not callback.message:
        return
    await state.clear()
    try:
        await callback.message.delete()
        await callback.answer("Ви вийшли з гри.")
    except TelegramAPIError:
        await callback.answer()

@reaction_router.callback_query(
    F.data == "reaction_game:show_leaderboard", StateFilter(ReactionGameState.menu)
)
async def show_leaderboard_callback_handler(callback: CallbackQuery):
    """Показує таблицю лідерів, оновлюючи повідомлення лобі."""
    if not callback.message:
        return
    leaderboard_data = await get_leaderboard(limit=10)
    if not leaderboard_data:
        text = "🏆 **Таблиця лідерів 'Світлофор'** 🏆\n\nРекордів ще немає. Будь першим!"
    else:
        response_lines = ["🏆 <b>Таблиця лідерів 'Світлофор'</b> 🏆\n"]
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        for i, record in enumerate(leaderboard_data):
            place = medals.get(i, f"  <b>{i + 1}.</b>")
            nickname = html.escape(record.get("nickname", "Анонім"))
            best_time = record.get("best_time", "N/A")
            response_lines.append(f"{place} {nickname} — <code>{best_time} мс</code>")
        text = "\n".join(response_lines)

    await callback.message.edit_text(
        text=text,
        reply_markup=create_leaderboard_view_keyboard(),
    )
    await callback.answer()

@reaction_router.callback_query(
    F.data == "reaction_game:stop", StateFilter(ReactionGameState.in_progress)
)
async def stop_reaction_game_handler(callback: CallbackQuery, state: FSMContext):
    """Обробляє натискання кнопки "СТОП" та розраховує результат."""
    if not callback.message:
        return

    end_time = time.monotonic()
    data = await state.get_data()
    green_light_time = data.get("green_light_time")
    
    await state.clear()

    if not green_light_time:
        result_text = "🔴 Фальстарт! 🔴\n\nТи натиснув ще до зеленого сигналу. Результат не зараховано."
        await callback.answer("Фальстарт!", show_alert=True)
    else:
        reaction_time_ms = int((end_time - green_light_time) * 1000)
        
        # ❗️ НОВЕ: Додавання цікавого факту
        fact = get_fact_for_time(reaction_time_ms)
        
        if reaction_time_ms < 100:
            result_text = f"🚀 Неймовірно! {reaction_time_ms} мс! 🚀\n\nЦе майже надлюдська реакція! Результат зараховано, але чи зможеш повторити?"
        else:
            result_text = f"🚀 Твій результат: <b>{reaction_time_ms} мс</b>!"
        
        result_text += f"\n\n<i>💡 {fact}</i>" # Додаємо факт до повідомлення
        
        await save_reaction_score(callback.from_user.id, reaction_time_ms)
        await callback.answer(f"Ваш час: {reaction_time_ms} мс")

    await callback.message.edit_text(result_text, reply_markup=None)


@reaction_router.message(Command("reaction_top"))
async def show_leaderboard_command_handler(message: Message):
    """Обробник команди /reaction_top для зворотної сумісності."""
    leaderboard_data = await get_leaderboard(limit=10)
    if not leaderboard_data:
        await message.answer("Рекордів ще немає. Зіграй у /reaction, щоб стати першим!")
        return

    response_lines = ["🏆 <b>Таблиця лідерів 'Світлофор'</b> 🏆\n"]
    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, record in enumerate(leaderboard_data):
        place = medals.get(i, f"  <b>{i + 1}.</b>")
        nickname = html.escape(record.get("nickname", "Анонім"))
        best_time = record.get("best_time", "N/A")
        response_lines.append(f"{place} {nickname} — <code>{best_time} мс</code>")
    await message.answer("\n".join(response_lines))


def register_reaction_handlers(dp):
    """Реєструє обробники гри в головному диспетчері."""
    dp.include_router(reaction_router)
    logger.info("✅ Обробники для гри 'Reaction Time' зареєстровано.")
