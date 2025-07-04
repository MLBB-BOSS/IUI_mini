#handlers/registration_handler.py
"""
Обробники для процесу реєстрації та управління профілем користувача.
"""
import html
import base64
import io
from typing import Dict, Any

from aiogram import Bot, F, Router, types, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import (
    create_profile_menu_keyboard, 
    create_delete_confirm_keyboard
)
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id, delete_user_by_telegram_id
from config import OPENAI_API_KEY, logger

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

async def show_profile_menu(message: types.Message, user_id: int):
    """Відображає профіль користувача та меню керування."""
    user_data = await get_user_by_telegram_id(user_id)
    if user_data:
        profile_text = format_profile_display(user_data)
        await message.answer(
            profile_text,
            reply_markup=create_profile_menu_keyboard(),
            parse_mode="HTML"
        )
    else:
        # Це не повинно трапитися, якщо логіка правильна, але це запобіжник
        await message.answer("Не вдалося знайти ваш профіль. Спробуйте почати з /profile.")

@registration_router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    """Центральна команда для управління профілем."""
    if not message.from_user: return
    await state.clear()
    
    user_id = message.from_user.id
    existing_user = await get_user_by_telegram_id(user_id)
    
    if existing_user:
        await show_profile_menu(message, user_id)
    else:
        await state.set_state(RegistrationFSM.waiting_for_basic_photo)
        await message.answer("👋 Вітаю! Схоже, ви тут уперше.\n\nДля створення профілю, будь ласка, надішліть мені скріншот вашого ігрового профілю (головна сторінка). 📸")

# --- Обробники для кнопок меню ---

@registration_router.callback_query(F.data == "profile_update_basic")
async def profile_update_basic_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.waiting_for_basic_photo)
    await callback.message.edit_text("Будь ласка, надішліть новий скріншот вашого основного профілю (де нікнейм, ID, ранг).")
    await callback.answer()

@registration_router.callback_query(F.data == "profile_add_stats")
async def profile_add_stats_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.waiting_for_stats_photo)
    await callback.message.edit_text("Надішліть скріншот вашої загальної статистики (розділ 'Statistics' -> 'All Seasons').")
    await callback.answer()

@registration_router.callback_query(F.data == "profile_add_heroes")
async def profile_add_heroes_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.waiting_for_heroes_photo)
    await callback.message.edit_text("Надішліть скріншот ваших улюблених героїв (розділ 'Favorite' -> 'All Seasons', топ-3).")
    await callback.answer()

# --- Універсальний обробник фото для всіх станів ---

@registration_router.message(
    StateFilter(
        RegistrationFSM.waiting_for_basic_photo,
        RegistrationFSM.waiting_for_stats_photo,
        RegistrationFSM.waiting_for_heroes_photo
    ),
    F.photo
)
async def handle_profile_update_photo(message: Message, state: FSMContext, bot: Bot):
    if not message.photo or not message.from_user: return

    current_state = await state.get_state()
    mode_map = {
        RegistrationFSM.waiting_for_basic_photo.state: 'basic',
        RegistrationFSM.waiting_for_stats_photo.state: 'stats',
        RegistrationFSM.waiting_for_heroes_photo.state: 'heroes'
    }
    analysis_mode = mode_map.get(current_state)
    if not analysis_mode:
        await message.reply("Сталася помилка стану. Будь ласка, почніть знову з /profile.")
        await state.clear()
        return

    thinking_msg = await message.reply(f"Аналізую ваш скріншот ({analysis_mode})... 🤖")
    
    try:
        largest_photo: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
        file_info = await bot.get_file(largest_photo.file_id)
        if not file_info.file_path:
            await thinking_msg.edit_text("Не вдалося отримати інформацію про файл.")
            return

        image_bytes_io = await bot.download_file(file_info.file_path)
        image_base64 = base64.b64encode(image_bytes_io.read()).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            analysis_result = await gpt.analyze_user_profile(image_base64, mode=analysis_mode)

        if not analysis_result or 'error' in analysis_result:
            error_msg = analysis_result.get('error', 'Не вдалося розпізнати дані.')
            await thinking_msg.edit_text(f"❌ Помилка аналізу: {error_msg}\n\nБудь ласка, надішліть коректний скріншот або скасуйте операцію.")
            return

        # Обробка результатів для різних режимів
        update_data = {}
        if analysis_mode == 'basic':
            # Збираємо дані з основного профілю
            update_data = {
                'nickname': analysis_result.get('game_nickname'),
                'player_id': int(analysis_result.get('mlbb_id_server', '0 (0)').split(' ')[0]),
                'server_id': int(analysis_result.get('mlbb_id_server', '0 (0)').split('(')[1].replace(')', '')),
                'current_rank': analysis_result.get('highest_rank_season'),
                'total_matches': analysis_result.get('matches_played')
            }
        elif analysis_mode == 'stats':
            # Збираємо дані зі статистики
            main_indicators = analysis_result.get('main_indicators', {})
            update_data = {
                'total_matches': main_indicators.get('matches_played'),
                'win_rate': main_indicators.get('win_rate')
            }
        elif analysis_mode == 'heroes':
            # Збираємо дані по героях
            heroes_list = analysis_result.get('favorite_heroes', [])
            heroes_str = ", ".join([h.get('hero_name', '') for h in heroes_list if h.get('hero_name')])
            update_data = {'favorite_heroes': heroes_str}

        # Видаляємо ключі з None, щоб не перезаписувати існуючі дані
        update_data = {k: v for k, v in update_data.items() if v is not None}

        if not update_data:
            await thinking_msg.edit_text("Не вдалося витягти жодних нових даних зі скріншота. Спробуйте ще раз.")
            return
            
        update_data['telegram_id'] = message.from_user.id
        await add_or_update_user(update_data)
        
        await thinking_msg.delete()
        await message.answer(f"✅ Дані '{analysis_mode}' успішно оновлено!")
        await show_profile_menu(message, message.from_user.id)

    except Exception as e:
        logger.exception(f"Критична помилка під час обробки фото (mode={analysis_mode}):")
        await thinking_msg.edit_text("Сталася неочікувана помилка. Спробуйте ще раз.")
    finally:
        await state.clear()


# --- Обробники видалення ---

@registration_router.callback_query(F.data == "profile_delete")
async def profile_delete_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationFSM.confirming_deletion)
    await callback.message.edit_text(
        "Ви впевнені, що хочете видалити свій профіль? Ця дія невідворотна.",
        reply_markup=create_delete_confirm_keyboard()
    )
    await callback.answer()

@registration_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_yes")
async def confirm_delete_profile(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user: return
    user_id = callback.from_user.id
    deleted = await delete_user_by_telegram_id(user_id)
    if deleted:
        await callback.message.edit_text("Ваш профіль було успішно видалено.")
        await callback.answer("Профіль видалено", show_alert=True)
    else:
        await callback.message.edit_text("Не вдалося видалити профіль. Можливо, його вже не існує.")
    await state.clear()

@registration_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_no")
async def cancel_delete_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete() # Видаляємо повідомлення з підтвердженням
    if callback.from_user:
        await show_profile_menu(callback.message, callback.from_user.id) # Показуємо меню знову
    await callback.answer("Дію скасовано.")

def register_registration_handlers(dp: Dispatcher):
    """Реєструє всі обробники, пов'язані з процесом реєстрації."""
    dp.include_router(registration_router)
    logger.info("✅ Обробники для реєстрації та управління профілем успішно зареєстровано.")
