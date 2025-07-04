"""
Обробники для процесу реєстрації, оновлення та видалення профілю користувача.
"""
import html
import base64
from aiogram import Bot, F, Router, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize

from states.user_states import RegistrationFSM
from services.openai_service import MLBBChatGPT
from database.crud import (
    add_or_update_user,
    get_user_by_telegram_id,
    delete_user
)
from keyboards.inline_keyboards import (
    create_registration_confirmation_keyboard,
    create_profile_menu_keyboard,
    create_delete_confirm_keyboard
)
from config import OPENAI_API_KEY, logger

# Ініціалізація роутера для профілю та реєстрації
profile_router = Router()


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


@profile_router.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    """Початок реєстрації або показ існуючого профілю."""
    user_id = message.from_user.id
    existing = await get_user_by_telegram_id(user_id)
    if existing:
        # Виводимо збережений профіль з меню управління
        txt = format_profile_data_for_confirmation(existing)
        await message.answer(txt, parse_mode="HTML", reply_markup=create_profile_menu_keyboard())
        return

    # Запит скріну для базової реєстрації
    await state.set_state(RegistrationFSM.waiting_for_photo)
    await message.answer("Надішліть скріншот вашого профілю для реєстрації. 📸")


@profile_router.message(RegistrationFSM.waiting_for_photo, F.photo)
async def handle_registration_photo(message: Message, state: FSMContext, bot: Bot):
    """Обробка базового профілю через скріншот."""
    thinking = await message.reply("Аналізую профіль... 🤖")
    try:
        # Завантаження фото та перетворення в base64
        largest: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
        file_info = await bot.get_file(largest.file_id)
        image_bytes = await bot.download_file(file_info.file_path)
        image_b64 = base64.b64encode(image_bytes.read()).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            result = await gpt.analyze_user_profile(image_b64)
        if not result or 'error' in result:
            raise ValueError(result.get('error', 'Невідома помилка'))

        await state.update_data(profile_data=result)

        text = (
            "Перевірте дані профілю:\n\n"
            f"{format_profile_data_for_confirmation(result)}\n\n"
            "Натисніть «Зберегти» або «Скасувати»"
        )
        await thinking.edit_text(text, reply_markup=create_registration_confirmation_keyboard(), parse_mode="HTML")
        await state.set_state(RegistrationFSM.waiting_for_confirmation)

    except Exception as e:
        logger.exception("Помилка аналізу фото:")
        await thinking.edit_text("Не вдалося розпізнати дані. Спробуйте інший скріншот.")
        await state.clear()


@profile_router.callback_query(RegistrationFSM.waiting_for_confirmation, F.data == "register_confirm")
async def confirm_registration(callback: CallbackQuery, state: FSMContext):
    """Збереження даних після підтвердження."""
    data = await state.get_data()
    profile = data.get('profile_data')
    profile['telegram_id'] = callback.from_user.id
    # Конвертуємо список героїв у рядок
    if isinstance(profile.get('favorite_heroes'), list):
        profile['favorite_heroes'] = ", ".join(profile['favorite_heroes'])

    await add_or_update_user(profile)
    await callback.message.edit_text("✅ Профіль успішно збережено.")
    await callback.answer()
    # Показ меню для наступних дій
    await callback.message.answer(
        format_profile_data_for_confirmation(profile),
        parse_mode="HTML",
        reply_markup=create_profile_menu_keyboard()
    )
    await state.clear()


@profile_router.callback_query(RegistrationFSM.waiting_for_confirmation, F.data == "register_cancel")
async def cancel_registration(callback: CallbackQuery, state: FSMContext):
    """Скасування реєстрації."""
    await state.clear()
    await callback.message.edit_text("Реєстрацію скасовано.")
    await callback.answer()


# ==== Обробники кнопок меню профілю ====
@profile_router.callback_query(F.data == "profile_update_basic")
async def update_basic(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Надішліть скріншот з базовою інформацією.",
        reply_markup=None
    )
    await state.set_state(RegistrationFSM.waiting_for_photo)

@profile_router.callback_query(F.data == "profile_add_stats")
async def update_stats(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Надішліть скріншот зі статистикою All Seasons.",
        reply_markup=None
    )
    await state.set_state(RegistrationFSM.waiting_for_stats_photo)

@profile_router.callback_query(F.data == "profile_add_heroes")
async def update_heroes(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Надішліть скріншот Favorite Heroes (Top 3).", reply_markup=None
    )
    await state.set_state(RegistrationFSM.waiting_for_heroes_photo)

@profile_router.callback_query(F.data == "profile_delete")
async def cb_delete_profile(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "Ви впевнені, що хочете видалити профіль?", reply_markup=create_delete_confirm_keyboard()
    )
    await state.set_state(RegistrationFSM.confirming_deletion)

@profile_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_yes")
async def cb_delete_yes(cb: CallbackQuery, state: FSMContext):
    await delete_user(cb.from_user.id)
    await cb.message.edit_text("Профіль видалено. Для нової реєстрації — /register")
    await state.clear()

@profile_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_no")
async def cb_delete_no(cb: CallbackQuery, state: FSMContext):
    user = await get_user_by_telegram_id(cb.from_user.id)
    txt = format_profile_data_for_confirmation(user)
    await cb.message.edit_text(
        txt, parse_mode="HTML", reply_markup=create_profile_menu_keyboard()
    )
    await state.clear()


def register_profile_handlers(dp: Dispatcher):
    dp.include_router(profile_router)
    logger.info("✅ Обробники профілю успішно зареєстровано.")
