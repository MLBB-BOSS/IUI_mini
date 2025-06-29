"""
Обробники для процесу реєстрації нового користувача.
"""
import html
import json
import base64
import io
from aiogram import Bot, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import create_registration_confirmation_keyboard
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id
from config import OPENAI_API_KEY, logger

# Ініціалізація роутера для реєстрації
registration_router = Router()

def format_profile_data_for_confirmation(data: dict) -> str:
    """Форматує дані профілю для повідомлення-підтвердження."""
    return (
        f"👤 <b>Нікнейм:</b> {html.escape(data.get('nickname', 'Не знайдено'))}\n"
        f"🆔 <b>ID:</b> {data.get('player_id', 'N/A')} ({data.get('server_id', 'N/A')})\n"
        f"🏆 <b>Ранг:</b> {html.escape(data.get('current_rank', 'Не знайдено'))}\n"
        f"⚔️ <b>Матчів:</b> {data.get('total_matches', 'Не знайдено')}\n"
        f"📊 <b>WR:</b> {data.get('win_rate', 'Не знайдено')}%\n\n"
        f"🦸 <b>Улюблені герої:</b>\n• {html.escape(data.get('favorite_heroes', 'Не знайдено'))}"
    )

@registration_router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """Починає процес реєстрації або показує існуючий профіль."""
    user_id = message.from_user.id
    
    existing_user = await get_user_by_telegram_id(user_id)
    if existing_user:
        profile_info = format_profile_data_for_confirmation(existing_user)
        await message.answer(f"Ви вже зареєстровані! Ось ваші дані:\n\n{profile_info}", parse_mode="HTML")
        return

    await state.set_state(RegistrationFSM.waiting_for_photo)
    await message.answer("Для реєстрації, будь ласка, надішліть мені скріншот вашого ігрового профілю. 📸")

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
        if not file_info.file_path: return

        image_bytes = await bot.download_file(file_info.file_path)
        if not isinstance(image_bytes, io.BytesIO): return
        
        image_base64 = base64.b64encode(image_bytes.getvalue()).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            # Використовуємо спеціалізований метод для аналізу профілю
            analysis_result = await gpt.analyze_user_profile(image_base64)

        if not analysis_result or 'error' in analysis_result:
            error_msg = analysis_result.get('error', 'Не вдалося розпізнати дані.')
            await thinking_msg.edit_text(f"Помилка аналізу: {error_msg} Спробуйте інший скріншот.")
            return
            
        # Зберігаємо розпізнані дані у FSM
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
        await thinking_msg.edit_text("Сталася помилка під час обробки фото. Спробуйте ще раз.")
        await state.clear()

@registration_router.callback_query(RegistrationFSM.waiting_for_confirmation, F.data == "register_confirm")
async def confirm_registration(callback: CallbackQuery, state: FSMContext):
    """Зберігає дані в БД після підтвердження користувачем."""
    user_data = await state.get_data()
    profile_data = user_data.get('profile_data')

    if not profile_data or not callback.from_user:
        await callback.message.edit_text("Помилка: дані для збереження не знайдено.")
        await state.clear()
        return

    # Додаємо Telegram ID до даних
    profile_data['telegram_id'] = callback.from_user.id
    
    await add_or_update_user(profile_data)
    
    await callback.message.edit_text("✅ Вітаю! Ваш профіль успішно збережено.")
    await callback.answer("Реєстрацію завершено!")
    await state.clear()

@registration_router.callback_query(RegistrationFSM.waiting_for_confirmation, F.data == "register_cancel")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    """Скасовує процес реєстрації."""
    await state.clear()
    await callback.message.edit_text("Реєстрацію скасовано. Ви можете почати знову, надіславши команду /register.")
    await callback.answer("Дію скасовано.")
    
# === 🆕 ФУНКЦІЯ РЕЄСТРАЦІЇ РОУТЕРА ===
def register_registration_handlers(dp: Dispatcher):
    """Реєструє всі обробники, пов'язані з процесом реєстрації."""
    dp.include_router(registration_router)
    logger.info("✅ Обробники для реєстрації користувачів успішно зареєстровано.")
