"""
Обробники для процесу реєстрації та управління профілем користувача
з реалізацією логіки "Чистого чату".
"""
import html
import base64
import io
from typing import Dict, Any, Optional

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.exceptions import TelegramAPIError

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import (
    create_profile_menu_keyboard,
    create_profile_menu_overview_keyboard,
    create_delete_confirm_keyboard
)
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id, delete_user_by_telegram_id
from config import OPENAI_API_KEY, logger
# 🆕 Імпорт менеджера для збереження файлів
from utils.file_manager import file_resilience_manager

registration_router = Router()


def format_profile_display(user_data: Dict[str, Any]) -> str:
    """Форматує дані профілю для відображення користувачу."""
    nickname = html.escape(user_data.get('nickname', 'Не вказано'))
    player_id = user_data.get('player_id', 'N/A')
    server_id = user_data.get('server_id', 'N/A')
    current_rank = html.escape(user_data.get('current_rank', 'Не вказано'))
    total_matches = user_data.get('total_matches', 'Не вказано')
    win_rate = user_data.get('win_rate')
    win_rate_str = f"{win_rate}%" if win_rate is not None else "Не вказано"
    heroes = user_data.get('favorite_heroes')
    heroes_str = html.escape(heroes) if heroes else "Не вказано"
    return (
        f"<b>Ваш профіль:</b>\n\n"
        f"👤 <b>Нікнейм:</b> {nickname}\n"
        f"🆔 <b>ID:</b> {player_id} ({server_id})\n"
        f"🏆 <b>Ранг:</b> {current_rank}\n"
        f"⚔️ <b>Матчів:</b> {total_matches}\n"
        f"📊 <b>WR:</b> {win_rate_str}\n"
        f"🦸 <b>Улюблені герої:</b> {heroes_str}"
    )


async def show_profile_menu(
    bot: Bot,
    chat_id: int,
    user_id: int,
    message_to_delete_id: int = None
):
    """Відображає профіль, видаляючи попереднє повідомлення для чистоти чату."""
    if message_to_delete_id:
        try:
            await bot.delete_message(chat_id, message_to_delete_id)
        except TelegramAPIError as e:
            logger.warning(f"Не вдалося видалити проміжне повідомлення {message_to_delete_id}: {e}")

    user_data = await get_user_by_telegram_id(user_id)
    if user_data:
        url = user_data.get('basic_profile_permanent_url')
        caption = format_profile_display(user_data)
        if url:
            await bot.send_photo(
                chat_id,
                url,
                caption=caption,
                reply_markup=create_profile_menu_keyboard(),
                parse_mode="HTML"
            )
        else:
            await bot.send_message(
                chat_id,
                caption,
                reply_markup=create_profile_menu_keyboard(),
                parse_mode="HTML"
            )
    else:
        await bot.send_message(
            chat_id,
            "Не вдалося знайти ваш профіль. Спробуйте почати з /profile."
        )


@registration_router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext, bot: Bot):
    """Центральна команда для управління профілем."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        await message.delete()
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити команду /profile: {e}")

    await state.clear()
    existing_user = await get_user_by_telegram_id(user_id)
    if existing_user:
        await show_profile_menu(bot, chat_id, user_id)
    else:
        await state.set_state(RegistrationFSM.waiting_for_basic_photo)
        sent = await bot.send_message(
            chat_id,
            "👋 Вітаю! Схоже, ви тут уперше.\n\n"
            "Для створення профілю, будь ласка, надішліть мені скріншот вашого ігрового профілю (головна сторінка). 📸"
        )
        await state.update_data(last_bot_message_id=sent.message_id)


# --- Обробники для оновлення через меню ---
@registration_router.callback_query(F.data == "profile_update_basic")
async def profile_update_basic_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.waiting_for_basic_photo)
    await callback.message.edit_text(
        "Будь ласка, надішліть новий скріншот вашого основного профілю "
        "(де нікнейм, ID, ранг)."
    )
    await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()


@registration_router.callback_query(F.data == "profile_update_stats")
async def profile_add_stats_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.waiting_for_stats_photo)
    await callback.message.edit_text(
        "Надішліть скріншот вашої загальної статистики "
        "(розділ 'Statistics' -> 'All Seasons')."
    )
    await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()


@registration_router.callback_query(F.data == "profile_update_heroes")
async def profile_add_heroes_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.waiting_for_heroes_photo)
    await callback.message.edit_text(
        "Надішліть скріншот ваших улюблених героїв "
        "(розділ 'Favorite' -> 'All Seasons', топ-3)."
    )
    await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()


# --- Універсальний обробник фото з "Чистим чатом" ---
@registration_router.message(
    StateFilter(
        RegistrationFSM.waiting_for_basic_photo,
        RegistrationFSM.waiting_for_stats_photo,
        RegistrationFSM.waiting_for_heroes_photo
    ),
    F.photo
)
async def handle_profile_update_photo(
    message: Message,
    state: FSMContext,
    bot: Bot
):
    if not message.photo or not message.from_user:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    data = await state.get_data()
    last_bot_message_id = data.get('last_bot_message_id')

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    current_state = await state.get_state()
    mode_map = {
        RegistrationFSM.waiting_for_basic_photo.state: 'basic',
        RegistrationFSM.waiting_for_stats_photo.state: 'stats',
        RegistrationFSM.waiting_for_heroes_photo.state: 'heroes'
    }
    analysis_mode = mode_map.get(current_state)
    if not analysis_mode or not last_bot_message_id:
        await bot.send_message(chat_id, "Сталася помилка стану. Почніть знову з /profile.")
        await state.clear()
        return

    thinking = await bot.edit_message_text(
        chat_id=chat_id,
        message_id=last_bot_message_id,
        text=f"Аналізую ваш скріншот ({analysis_mode})... 🤖"
    )

    try:
        largest: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
        file_info = await bot.get_file(largest.file_id)
        if not file_info.file_path:
            await thinking.edit_text("Не вдалося отримати інформацію про файл.")
            return

        file_bytes_io = await bot.download_file(file_info.file_path)
        image_bytes = file_bytes_io.read()
        permanent_url = await file_resilience_manager.optimize_and_store_image(
            image_bytes, user_id, analysis_mode
        )

        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            analysis_result = await gpt.analyze_user_profile(image_b64, mode=analysis_mode)

        if not analysis_result or 'error' in analysis_result:
            err = analysis_result.get('error', 'Не вдалося розпізнати дані.')
            await thinking.edit_text(f"❌ Помилка аналізу: {err}\n\nБудь ласка, спробуйте ще раз.")
            await state.clear()
            return

        update_data: Dict[str, Any] = {}
        if analysis_mode == 'basic':
            ml = analysis_result.get('mlbb_id_server', '0 (0)').split()
            pid = int(ml[0])
            sid = int(ml[1].strip("()"))
            update_data = {
                'nickname': analysis_result.get('game_nickname'),
                'player_id': pid,
                'server_id': sid,
                'current_rank': analysis_result.get('highest_rank_season'),
                'total_matches': analysis_result.get('matches_played'),
                'basic_profile_file_id': largest.file_id,
                'basic_profile_permanent_url': permanent_url
            }
        elif analysis_mode == 'stats':
            main = analysis_result.get('main_indicators', {})
            update_data = {
                'total_matches': main.get('matches_played'),
                'win_rate': main.get('win_rate'),
                'stats_photo_file_id': largest.file_id,
                'stats_photo_permanent_url': permanent_url
            }
        else:  # heroes
            fav = analysis_result.get('favorite_heroes', [])
            heroes_str = ", ".join(h.get('hero_name', '') for h in fav if h.get('hero_name'))
            update_data = {
                'favorite_heroes': heroes_str,
                'heroes_photo_file_id': largest.file_id,
                'heroes_photo_permanent_url': permanent_url
            }

        update_data = {k: v for k, v in update_data.items() if v is not None}
        update_data['telegram_id'] = user_id

        status = await add_or_update_user(update_data)
        if status == 'success':
            await show_profile_menu(
                bot, chat_id, user_id, message_to_delete_id=thinking.message_id
            )
        elif status == 'conflict':
            await thinking.edit_text(
                "🛡️ <b>Конфлікт реєстрації!</b>\n\n"
                "Цей профіль вже зареєстровано іншим акаунтом Telegram."
            )
        else:
            await thinking.edit_text("❌ Сталася помилка при збереженні. Спробуйте пізніше.")

    except Exception as e:
        logger.exception(f"Критична помилка під час обробки фото (mode={analysis_mode}): {e}")
        await thinking.edit_text("Сталася неочікувана помилка. Спробуйте ще раз.")
    finally:
        await state.clear()


# === 🔄 НОВІ ОБРОБНИКИ ДЛЯ МЕНЮ ===
@registration_router.callback_query(F.data == "profile_show_menu")
async def profile_show_menu_handler(callback: CallbackQuery):
    """
    Відкриває розгорнуте меню профілю.
    """
    # За потреби можна тут обчислити фактичну кількість сторінок
    await callback.message.edit_reply_markup(
        reply_markup=create_profile_menu_overview_keyboard(current_page=1, total_pages=1)
    )
    await callback.answer()


@registration_router.callback_query(F.data == "profile_hide_menu")
async def profile_hide_menu_handler(callback: CallbackQuery):
    """
    Приховує розгорнуте меню, повертаючись до однокнопкового режиму.
    """
    await callback.message.edit_reply_markup(
        reply_markup=create_profile_menu_keyboard()
    )
    await callback.answer()


@registration_router.callback_query(F.data == "profile_delete")
async def profile_delete_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.confirming_deletion)
    await callback.message.edit_text(
        "Ви впевнені, що хочете видалити свій профіль? Ця дія невідворотна.",
        reply_markup=create_delete_confirm_keyboard()
    )
    await callback.answer()


@registration_router.callback_query(
    RegistrationFSM.confirming_deletion,
    F.data == "delete_confirm_yes"
)
async def confirm_delete_profile(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    deleted = await delete_user_by_telegram_id(user_id)
    if deleted:
        await callback.message.edit_text("Ваш профіль було успішно видалено.")
    else:
        await callback.message.edit_text("Не вдалося видалити профіль.")
    await callback.answer()
    await state.clear()


@registration_router.callback_query(
    RegistrationFSM.confirming_deletion,
    F.data == "delete_confirm_no"
)
async def cancel_delete_profile(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    await state.clear()
    await show_profile_menu(
        bot, chat_id, user_id, message_to_delete_id=callback.message.message_id
    )
    await callback.answer("Дію скасовано.")


def register_registration_handlers(dp: Router):
    """Реєструє всі обробники, пов'язані з процесом реєстрації."""
    dp.include_router(registration_router)
    logger.info("✅ Обробники для реєстрації успішно зареєстровано.")
