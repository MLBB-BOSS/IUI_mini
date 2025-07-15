"""
Обробники для міні-гри на перевірку реакції.
"""
import asyncio
import random
import time
from contextlib import suppress

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command

from config import logger
from database.crud import get_user_by_telegram_id
from games.reaction.crud import get_leaderboard, save_reaction_score
from games.reaction.facts import get_fact_for_time
from games.reaction.keyboards import (create_leaderboard_keyboard,
                                      create_reaction_game_keyboard)
# ❗️ НОВЕ: Імпортуємо повідомлення
from games.reaction.messages import (MSG_ERROR_NO_MESSAGE,
                                     MSG_ERROR_NOT_REGISTERED, MSG_GAME_OVER,
                                     MSG_GAME_TITLE, MSG_PREPARE, MSG_SUBTITLE,
                                     MSG_TOO_EARLY, get_leaderboard_text,
                                     get_loading_text, get_personal_best_text,
                                     get_result_text, get_user_time_answer,
                                     MSG_PRESS_NOW, MSG_FALSE_START, MSG_NEW_TOP_10_ENTRY)

# Словник для зберігання активних ігор
active_games: dict[int, dict] = {}
reaction_router = Router()


async def cmd_reaction(message: types.Message):
    """
    Обробник команди /reaction.
    Надсилає початкове меню гри на реакцію.
    """
    await message.answer(
        f"{MSG_GAME_TITLE}\n\n{MSG_SUBTITLE}",
        reply_markup=create_reaction_game_keyboard("initial", 0)
    )


async def start_reaction_game(callback_query: types.CallbackQuery):
    """
    Запускає новий раунд гри на реакцію.
    Показує анімацію завантаження з кружечків.
    """
    user_id = callback_query.from_user.id
    message = callback_query.message

    if not message:
        await callback_query.answer(MSG_ERROR_NO_MESSAGE, show_alert=True)
        return

    # Перевірка, чи гравець зареєстрований
    user_profile = await get_user_by_telegram_id(user_id)
    if not user_profile:
        await callback_query.answer(MSG_ERROR_NOT_REGISTERED, show_alert=True)
        return

    game_id = message.message_id
    active_games[game_id] = {"status": "running", "start_time": None}
    await callback_query.answer(MSG_PREPARE)

    try:
        # Анімація завантаження
        for i in range(1, 6):
            if game_id not in active_games or active_games[game_id]["status"] != "running":
                return
            
            loading_bar = "🔴" * i + "⚪️" * (5 - i)
            await message.edit_text(
                get_loading_text(loading_bar),
                reply_markup=create_reaction_game_keyboard("wait", game_id)
            )
            await asyncio.sleep(random.uniform(0.3, 0.8))

        # Рандомна затримка перед зміною кольору
        await asyncio.sleep(random.uniform(1.0, 4.0))

        if game_id in active_games and active_games[game_id]["status"] == "running":
            active_games[game_id]["start_time"] = time.monotonic()
            logger.info(f"Game ({game_id}): Light is GREEN at {active_games[game_id]['start_time']}")
            await message.edit_text(
                MSG_PRESS_NOW,
                reply_markup=create_reaction_game_keyboard("ready", game_id)
            )
    except TelegramAPIError as e:
        logger.error(f"Error during game animation for game {game_id}: {e}")
        if game_id in active_games:
            del active_games[game_id]


async def stop_reaction_game_handler(callback_query: types.CallbackQuery):
    """
    Обробляє натискання на кнопку, коли вона стала зеленою.
    """
    user_id = callback_query.from_user.id
    message = callback_query.message
    game_id = message.message_id if message else None

    if not message or game_id not in active_games or active_games[game_id]["status"] != "running":
        await callback_query.answer(MSG_GAME_OVER, show_alert=True)
        return

    start_time = active_games[game_id].get("start_time")
    if not start_time:
        # Фальстарт
        active_games[game_id]["status"] = "finished"
        await message.edit_text(
            MSG_FALSE_START,
            reply_markup=create_reaction_game_keyboard("finished", game_id)
        )
        await callback_query.answer(MSG_TOO_EARLY, show_alert=True)
        return

    reaction_time = time.monotonic() - start_time
    reaction_time_ms = int(reaction_time * 1000)
    active_games[game_id]["status"] = "finished"

    leaderboard_before = await get_leaderboard(limit=10)
    await save_reaction_score(user_id, reaction_time_ms)
    leaderboard_after = await get_leaderboard(limit=10)

    user_in_top_before = any(p["telegram_id"] == user_id for p in leaderboard_before)
    user_in_top_after = any(p["telegram_id"] == user_id for p in leaderboard_after)
    
    new_best_text = ""
    if user_in_top_after and not user_in_top_before:
        new_best_text = MSG_NEW_TOP_10_ENTRY
    elif user_in_top_after:
        pos_before = next((i for i, p in enumerate(leaderboard_before) if p["telegram_id"] == user_id), 11)
        pos_after = next((i for i, p in enumerate(leaderboard_after) if p["telegram_id"] == user_id), 11)
        if pos_after < pos_before:
            new_best_text = get_personal_best_text(pos_after + 1)
    
    fact = get_fact_for_time(reaction_time_ms)
    result_text = get_result_text(reaction_time_ms, new_best_text, fact)
    leaderboard_text = get_leaderboard_text(leaderboard_after, user_id)
        
    final_text = result_text + "\n\n" + leaderboard_text

    await message.edit_text(
        final_text,
        reply_markup=create_reaction_game_keyboard("finished", game_id)
    )
    await callback_query.answer(get_user_time_answer(reaction_time_ms))
    
    with suppress(KeyError):
        del active_games[game_id]


async def show_leaderboard(callback_query: types.CallbackQuery):
    """Показує актуальну таблицю лідерів."""
    leaderboard_data = await get_leaderboard(limit=10)
    text = get_leaderboard_text(leaderboard_data, callback_query.from_user.id)
        
    await callback_query.message.edit_text(
        text,
        reply_markup=create_leaderboard_keyboard()
    )
    await callback_query.answer()


async def back_to_game_menu(callback_query: types.CallbackQuery):
    """Повертає до початкового меню гри."""
    await callback_query.message.edit_text(
        f"{MSG_GAME_TITLE}\n\n{MSG_SUBTITLE}",
        reply_markup=create_reaction_game_keyboard("initial", 0)
    )
    await callback_query.answer()


def register_reaction_handlers(dp: Router):
    """Реєструє всі обробники для гри 'Reaction Time'."""
    dp.message.register(cmd_reaction, Command("reaction"))
    dp.callback_query.register(start_reaction_game, F.data == "reaction_game_start")
    dp.callback_query.register(stop_reaction_game_handler, F.data.startswith("reaction_game_press:"))
    dp.callback_query.register(show_leaderboard, F.data == "reaction_game_leaderboard")
    dp.callback_query.register(back_to_game_menu, F.data == "reaction_game_back_to_menu")
    logger.info("✅ Обробники для гри 'Reaction Time' зареєстровано.")
