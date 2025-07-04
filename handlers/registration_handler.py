"""
Обробники для реєстрації, керування та оновлення профілю користувача.
"""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from states.profile_states import ProfileRegistration
from keyboards.profile_keyboards import get_profile_menu_keyboard, get_confirm_delete_keyboard
from database.crud import get_user_by_telegram_id, add_or_update_user, delete_user
from config import logger

# Уявімо, що у вас є функція для аналізу скріншотів
# from vision.analyzer import analyze_screenshot

# --- Mock-функція для аналізу скріншотів ---
# ЗАМІНІТЬ ЦЕ НА ВАШУ РЕАЛЬНУ ФУНКЦІЮ
async def analyze_screenshot(photo: bytes, mode: str) -> dict:
    """
    Mock-функція для імітації аналізу скріншоту.
    У реальному проєкті тут буде виклик вашого Vision-модуля.
    """
    logger.info(f"Аналіз скріншоту в режимі: {mode}")
    if mode == "basic":
        return {"nickname": "MockPlayer", "player_id": 12345678, "server_id": 1234, "current_rank": "Міфічний"}
    if mode == "stats":
        return {"total_matches": 1500, "win_rate": 55.5}
    if mode == "heroes":
        return {"favorite_heroes": "Фанні, Лін, Грейнджер"}
    return {}
# --- Кінець Mock-функції ---

router = Router()

def format_profile_message(user_data: dict) -> str:
    """Форматує повідомлення з даними профілю."""
    lines = [
        f"👤 **Профіль гравця @{user_data.get('nickname', 'N/A')}**",
        "",
        f"**Базова інформація:**",
        f"  - ID гравця: `{user_data.get('player_id', 'Не вказано')}` (Сервер: `{user_data.get('server_id', 'N/A')}`)",
        f"  - Поточний ранг: {user_data.get('current_rank', 'Не вказано')}",
        "",
        "**Загальна статистика:**",
        f"  - Всього матчів: {user_data.get('total_matches', 'Не вказано')}",
        f"  - Відсоток перемог: {user_data.get('win_rate', 'N/A')}%",
        "",
        "**Улюблені герої:**",
        f"  - {user_data.get('favorite_heroes', 'Не вказано')}",
    ]
    return "\n".join(lines)

@router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """Починає процес початкової реєстрації."""
    user_id = message.from_user.id
    user_profile = await get_user_by_telegram_id(user_id)

    if user_profile:
        await message.answer("Ви вже зареєстровані. Ось ваш профіль:")
        profile_text = format_profile_message(user_profile)
        await message.answer(profile_text, reply_markup=get_profile_menu_keyboard())
        return

    await state.set_state(ProfileRegistration.waiting_for_initial_photo)
    await message.answer(
        "👋 Вітаю! Для реєстрації профілю, будь ласка, надішліть мені скріншот вашого **основного екрану профілю** в Mobile Legends."
    )

@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext):
    """Показує профіль користувача та меню керування."""
    await state.clear()
    user_profile = await get_user_by_telegram_id(message.from_user.id)
    if not user_profile:
        await message.answer("Профіль не знайдено. Будь ласка, пройдіть реєстрацію за допомогою команди /register.")
        return

    profile_text = format_profile_message(user_profile)
    await message.answer(profile_text, reply_markup=get_profile_menu_keyboard())

# Обробник для всіх фотографій, що надходять у станах FSM
@router.message(F.photo, ProfileRegistration)
async def handle_profile_photo(message: Message, state: FSMContext, bot: Bot):
    """Обробляє отримані скріншоти для реєстрації або оновлення."""
    current_state = await state.get_state()
    user_id = message.from_user.id
    
    modes = {
        ProfileRegistration.waiting_for_initial_photo: "basic",
        ProfileRegistration.waiting_for_basic_photo_update: "basic",
        ProfileRegistration.waiting_for_stats_photo_update: "stats",
        ProfileRegistration.waiting_for_heroes_photo_update: "heroes",
    }
    
    mode = modes.get(current_state)
    if not mode:
        return

    await message.answer("⏳ Аналізую скріншот... Це може зайняти трохи часу.")
    
    # Завантажуємо фото
    photo_bytes = await bot.download(message.photo[-1])
    # Викликаємо аналіз
    extracted_data = await analyze_screenshot(photo_bytes.read(), mode)

    if not extracted_data:
        await message.answer("❌ Не вдалося розпізнати дані на скріншоті. Будь ласка, спробуйте ще раз, надіславши чітке та необрізане зображення.")
        return

    # Отримуємо поточний профіль, щоб оновити його
    user_profile = await get_user_by_telegram_id(user_id) or {"telegram_id": user_id}
    user_profile.update(extracted_data) # Оновлюємо словник новими даними

    await add_or_update_user(user_profile)
    
    success_message = {
        "basic": "✅ Базові дані профілю успішно оновлено!",
        "stats": "✅ Загальну статистику додано/оновлено!",
        "heroes": "✅ Статистику героїв додано/оновлено!",
    }[mode]
    
    await message.answer(success_message)
    
    # Показуємо оновлений профіль
    updated_profile = await get_user_by_telegram_id(user_id)
    profile_text = format_profile_message(updated_profile)
    await message.answer(profile_text, reply_markup=get_profile_menu_keyboard())
    
    await state.clear()

# --- Обробники для кнопок меню ---

@router.callback_query(F.data == "profile_update_basic")
async def cb_update_basic(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileRegistration.waiting_for_basic_photo_update)
    await callback.message.answer("Будь ласка, надішліть новий скріншот **основного екрану профілю**.")
    await callback.answer()

@router.callback_query(F.data == "profile_add_stats")
async def cb_add_stats(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileRegistration.waiting_for_stats_photo_update)
    await callback.message.answer("Будь ласка, надішліть скріншот вкладки **'Статистика' -> 'Всі сезони'**.")
    await callback.answer()

@router.callback_query(F.data == "profile_add_heroes")
async def cb_add_heroes(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileRegistration.waiting_for_heroes_photo_update)
    await callback.message.answer("Будь ласка, надішліть скріншот вкладки **'Улюблені герої' -> 'Всі сезони'** (повинно бути видно топ-3).")
    await callback.answer()

@router.callback_query(F.data == "profile_delete")
async def cb_delete_profile(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileRegistration.confirming_deletion)
    await callback.message.edit_text(
        "**Ви впевнені, що хочете видалити свій профіль?**\n\nЦю дію неможливо буде скасувати.",
        reply_markup=get_confirm_delete_keyboard()
    )
    await callback.answer()

# --- Обробники для підтвердження видалення ---

@router.callback_query(F.data == "confirm_delete_yes", ProfileRegistration.confirming_deletion)
async def cb_confirm_delete(callback: CallbackQuery, state: FSMContext):
    deleted = await delete_user(callback.from_user.id)
    if deleted:
        await callback.message.edit_text("✅ Ваш профіль було успішно видалено.")
    else:
        await callback.message.edit_text("❌ Не вдалося видалити профіль. Можливо, його вже не існує.")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "confirm_delete_no", ProfileRegistration.confirming_deletion)
async def cb_cancel_delete(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_profile = await get_user_by_telegram_id(callback.from_user.id)
    if not user_profile:
        await callback.message.edit_text("Профіль не знайдено. /register, щоб почати.")
        return
        
    profile_text = format_profile_message(user_profile)
    await callback.message.edit_text(profile_text, reply_markup=get_profile_menu_keyboard())
    await callback.answer("Видалення скасовано.")

def register_registration_handlers(dp):
    """Реєструє всі обробники, пов'язані з профілем."""
    dp.include_router(router)
