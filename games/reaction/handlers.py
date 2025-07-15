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
from games.reaction.facts import get_fact_for_time
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
    await state.set_state(ReactionGameState.menu)
    sent_message = await message.answer(
        text=LOBBY_MESSAGE_TEXT,
        reply_markup=create_reaction_lobby_keyboard(),
    )
    await state.update_data(lobby_message_id=sent_message.message_id)

@reaction_router.message(Command("reaction"))
async def reaction_command_handler(message: Message, state: FSMContext):
    await show_lobby(message, state)

@reaction_router.callback_query(
    F.data == "reaction_game:show_lobby", StateFilter(ReactionGameState.menu)
)
async def show_lobby_callback_handler(callback: CallbackQuery, state: FSMContext):
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

# ❗️ НОВА, РОЗШИРЕНА ЛОГІКА ОБРОБКИ РЕЗУЛЬТАТІВ
@reaction_router.callback_query(
    F.data == "reaction_game:stop", StateFilter(ReactionGameState.in_progress)
)
async def stop_reaction_game_handler(callback: CallbackQuery, state: FSMContext):
    """
    Обробляє натискання кнопки "СТОП", розраховує результат,
    перевіряє рекорди та показує контекстну таблицю лідерів.
    """
    if not callback.message:
        return

    end_time = time.monotonic()
    data = await state.get_data()
    green_light_time = data.get("green_light_time")
    
    await state.clear()

    if not green_light_time:
        result_text = "🔴 Фальстарт! 🔴\n\nТи натиснув ще до зеленого сигналу. Результат не зараховано."
        await callback.answer("Фальстарт!", show_alert=True)
        await callback.message.edit_text(result_text, reply_markup=None)
        return

    reaction_time_ms = int((end_time - green_light_time) * 1000)
    user_id = callback.from_user.id

    # Крок 1: Отримати таблицю лідерів ДО оновлення
    leaderboard_before = await get_leaderboard(limit=10)
    personal_best = next(
        (p["best_time"] for p in leaderboard_before if p["telegram_id"] == user_id), 99999
    )

    # Крок 2: Зберегти новий результат
    await save_reaction_score(user_id, reaction_time_ms)
    
    # Крок 3: Отримати таблицю лідерів ПІСЛЯ оновлення
    leaderboard_after = await get_leaderboard(limit=10)
    new_pos = next(
        (i + 1 for i, p in enumerate(leaderboard_after) if p["telegram_id"] == user_id), -1
    )

    # Крок 4: Сформувати динамічне повідомлення
    record_message = ""
    if reaction_time_ms < personal_best:
        if new_pos != -1:
            record_message = f"🎉 <b>Новий рекорд!</b> Ти тепер на <b>{new_pos}-му місці</b>!\n\n"
        else:
            record_message = "🎉 <b>Новий особистий рекорд!</b>\n\n"

    result_text = f"🚀 Твій результат: <b>{reaction_time_ms} мс</b> <i>({reaction_time_ms / 1000.0:.3f} сек)</i>"
    fact_text = f"💡 <i>{get_fact_for_time(reaction_time_ms)}</i>"

    # Форматуємо таблицю лідерів
    leaderboard_lines = ["\n\n🏆 <b>Таблиця лідерів:</b>"]
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, record in enumerate(leaderboard_after):
        rank = i + 1
        place = medals.get(rank, f"  <b>{rank}.</b>")
        nickname = html.escape(record.get("nickname", "Анонім"))
        best_time = record.get("best_time", "N/A")
        line = f"{place} {nickname} — <code>{best_time} мс</code>"
        if record["telegram_id"] == user_id:
            line = f"<b>➡️ {line} ⬅️</b>"
        leaderboard_lines.append(line)
        
    leaderboard_text = "\n".join(leaderboard_lines)

    # Збираємо все разом
    final_text = record_message + result_text + "\n" + fact_text + leaderboard_text
    
    await callback.message.edit_text(final_text, reply_markup=None)
    await callback.answer(f"Ваш час: {reaction_time_ms} мс")

@reaction_router.message(Command("reaction_top"))
async def show_leaderboard_command_handler(message: Message):
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
    dp.include_router(reaction_router)
    logger.info("✅ Обробники для гри 'Reaction Time' зареєстровано.")
