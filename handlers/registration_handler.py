#handlers/registration_handler.py 
"""
Обробники для процесу реєстрації нового користувача.
"""
import html
import json
import base64
import io
from aiogram import Bot, F, Router, types, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import create_registration_confirmation_keyboard, create_profile_menu_keyboard, create_delete_confirm_keyboard
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id, delete_user_by_telegram_id
from config import OPENAI_API_KEY, logger

# Ініціалізація роутера для реєстрації
registration_router = Router()

def format_profile_data_for_confirmation(data: dict) -> str:
    """Форматує дані профілю для повідомлення-підтвердження."""
    win_rate = data.get('win_rate')
    win_rate_str = f"{win_rate}%" if win_rate is not None else "Не знайдено"

    heroes = data.get('favorite_heroes', 'Не знайдено')
    if isinstance(heroes, list):
        heroes_str = ", ".join(heroes)
    else:
        heroes_str = heroes if heroes is not None else "Не знайдено"

    return (
        f"👤 <b>Нікнейм:</b> {html.escape(str(data.get('nickname', 'Не знайдено')))}\n"
        f"🆔 <b>ID:</b> {data.get('player_id', 'N/A')} ({data.get('server_id', 'N/A')})\n"
        f"🏆 <b>Ранг:</b> {html.escape(str(data.get('current_rank', 'Не знайдено')))}\n"
        f"⚔️ <b>Матчів:</b> {data.get('total_matches', 'Не знайдено')}\n"
        f"📊 <b>WR:</b> {win_rate_str}\n\n"
        f"🦸 <b>Улюблені герої:</b>\n• {html.escape(str(heroes_str))}"
    )

@registration_router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    """
    Центральна команда для управління профілем.
    - Якщо користувач не зареєстрований, починає реєстрацію.
    - Якщо зареєстрований, показує меню управління профілем.
    """
    if not message.from_user:
        return

    user_id = message.from_user.id
    
    existing_user = await get_user_by_telegram_id(user_id)
    if existing_user:
        profile_info = format_profile_data_for_confirmation(existing_user)
        await message.answer(
            f"Ваш профіль:\n\n{profile_info}",
            reply_markup=create_profile_menu_keyboard(),
            parse_mode="HTML"
        )
    else:
        await state.set_state(RegistrationFSM.waiting_for_photo)
        await message.answer("Ви ще не зареєстровані. Для створення профілю, будь ласка, надішліть мені скріншот вашого ігрового профілю. 📸")

@registration_router.callback_query(F.data == "profile_update")
async def profile_update_handler(callback: CallbackQuery, state: FSMContext):
    """Обробляє запит на оновлення профілю."""
    await state.set_state(RegistrationFSM.waiting_for_photo)
    await callback.message.edit_text("Будь ласка, надішліть новий скріншот вашого профілю для оновлення.")
    await callback.answer()

@registration_router.callback_query(F.data == "profile_delete")
async def profile_delete_handler(callback: CallbackQuery, state: FSMContext):
    """Починає процес видалення профілю, запитуючи підтвердження."""
    await state.set_state(RegistrationFSM.confirming_deletion)
    await callback.message.edit_text(
        "Ви впевнені, що хочете видалити свій профіль? Ця дія невідворотна.",
        reply_markup=create_delete_confirm_keyboard()
    )
    await callback.answer()

@registration_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_yes")
async def confirm_delete_profile(callback: CallbackQuery, state: FSMContext):
    """Видаляє профіль після підтвердження."""
    if not callback.from_user:
        return
    user_id = callback.from_user.id
    try:
        deleted = await delete_user_by_telegram_id(user_id)
        if deleted:
            await callback.message.edit_text("Ваш профіль було успішно видалено.")
            await callback.answer("Профіль видалено", show_alert=True)
        else:
            await callback.message.edit_text("Не вдалося видалити профіль. Можливо, його вже не існує.")
            await callback.answer("Помилка видалення", show_alert=True)
    except Exception as e:
        logger.exception(f"Помилка під час видалення користувача {user_id} з БД:")
        await callback.message.edit_text("Сталася помилка під час видалення профілю. Спробуйте пізніше.")
    finally:
        await state.clear()


@registration_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_no")
async def cancel_delete_profile(callback: CallbackQuery, state: FSMContext):
    """Скасовує видалення профілю."""
    await state.clear()
    await callback.message.edit_text("Видалення скасовано. Ваш профіль у безпеці! 😊")
    await callback.answer("Дію скасовано.")

@registration_router.message(RegistrationFSM.waiting_for_photo, F.photo)
async def handle_registration_photo(message: Message, state: FSMContext, bot: Bot):
    """Обробляє скріншот профілю, аналізує його та просить підтвердження."""
    if not message.photo or not message.from_user:
        await message.reply("Будь ласка, надішліть зображення.")
        return

    thinking_msg = await message.reply("Аналізую ваш профіль... 🤖 Це може зайняти до 30 секунд.")
    
    try:
        largest_photo: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
        file_info = await bot.get_file(largest_photo.file_id)
        if not file_info.file_path:
            await thinking_msg.edit_text("Не вдалося отримати інформацію про файл.")
            return

        image_bytes_io = await bot.download_file(file_info.file_path)
        if not image_bytes_io:
             await thinking_msg.edit_text("Не вдалося завантажити зображення.")
             return
        
        image_base64 = base64.b64encode(image_bytes_io.read()).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            analysis_result = await gpt.analyze_user_profile(image_base64)

        if not analysis_result or 'error' in analysis_result:
            error_msg = analysis_result.get('error', 'Не вдалося розпізнати дані.')
            await thinking_msg.edit_text(f"Помилка аналізу: {error_msg} Спробуйте інший скріншот.")
            await state.clear()
            return
            
        await state.update_data(profile_data=analysis_result)
        
        confirmation_text = (
            "Будь ласка, перевірте розпізнані дані:\n\n"
            f"{format_profile_data_for_confirmation(analysis_result)}\n\n"
            "Якщо все вірно, натисніть 'Зберегти'."
        )
        
        await thinking_msg.edit_text(
            confirmation_text,
            reply_markup=create_registration_confirmation_keyboard(),
            parse_mode="HTML"
        )
        await state.set_state(RegistrationFSM.waiting_for_confirmation)

    except Exception as e:
        logger.exception("Критична помилка під час аналізу фото для реєстрації:")
        await thinking_msg.edit_text("Сталася неочікувана помилка під час обробки фото. Спробуйте ще раз.")
        await state.clear()

@registration_router.callback_query(RegistrationFSM.waiting_for_confirmation, F.data == "register_confirm")
async def confirm_registration(callback: CallbackQuery, state: FSMContext):
    """Зберігає дані в БД після підтвердження користувачем."""
    if not callback.message or not callback.from_user:
        return
        
    user_data = await state.get_data()
    profile_data = user_data.get('profile_data')

    if not profile_data:
        await callback.message.edit_text("Помилка: дані для збереження не знайдено. Спробуйте знову.")
        await state.clear()
        return

    profile_data['telegram_id'] = callback.from_user.id
    
    if 'favorite_heroes' in profile_data and isinstance(profile_data['favorite_heroes'], list):
        profile_data['favorite_heroes'] = ", ".join(profile_data['favorite_heroes'])

    try:
        await add_or_update_user(profile_data)
        await callback.message.edit_text("✅ Вітаю! Ваш профіль успішно збережено.")
        await callback.answer("Реєстрацію завершено!")
    except Exception as e:
        logger.exception("Помилка під час збереження даних користувача в БД:")
        await callback.message.edit_text("Помилка збереження даних. Спробуйте пізніше.")
    finally:
        await state.clear()

@registration_router.callback_query(RegistrationFSM.waiting_for_confirmation, F.data == "register_cancel")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    """Скасовує процес реєстрації."""
    if not callback.message:
        return
    await state.clear()
    await callback.message.edit_text("Реєстрацію скасовано. Ви можете почати знову, надіславши команду /register.")
    await callback.answer("Дію скасовано.")


def register_registration_handlers(dp: Dispatcher):
    """Реєструє всі обробники, пов'язані з процесом реєстрації."""
    dp.include_router(registration_router)
    logger.info("✅ Обробники для реєстрації користувачів успішно зареєстровано.")
