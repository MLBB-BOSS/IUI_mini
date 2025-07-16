"""
Обробники для налаштувань користувача, таких як ввімкнення/вимкнення функцій бота.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from database.crud import get_user_settings, update_user_settings
from keyboards.inline_keyboards import create_mute_settings_keyboard
from utils.cache_manager import clear_user_cache
from config import logger

settings_router = Router()

SETTINGS_MENU_TEXT = (
    "⚙️ **Керування налаштуваннями**\n\n"
    "Тут ви можете вмикати або вимикати реакції бота на ваші дії. "
    "Натисніть на кнопку, щоб змінити її стан."
)

async def _show_or_update_settings_menu(message: Message | CallbackQuery):
    """Допоміжна функція для показу або оновлення меню налаштувань."""
    user_id = message.from_user.id
    
    # Отримуємо налаштування з кешу або БД
    settings = await get_user_settings(user_id)
    keyboard = create_mute_settings_keyboard(settings)

    try:
        if isinstance(message, Message):
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=SETTINGS_MENU_TEXT,
                reply_markup=keyboard
            )
        elif isinstance(message, CallbackQuery) and message.message:
            await message.message.edit_text(
                text=SETTINGS_MENU_TEXT,
                reply_markup=keyboard
            )
            await message.answer() # Відповідаємо на callback, щоб годинник зник
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug(f"Menu not modified for user {user_id}.")
            if isinstance(message, CallbackQuery):
                await message.answer("Налаштування вже оновлено.")
        else:
            logger.error(f"Error updating settings menu for {user_id}: {e}")

@settings_router.message(Command("mute", "settings"))
async def cmd_mute_settings(message: Message):
    """Обробник команд /mute та /settings. Показує меню налаштувань."""
    if not message.from_user:
        return
    logger.info(f"User {message.from_user.id} requested settings menu.")
    await _show_or_update_settings_menu(message)


@settings_router.callback_query(F.data.startswith("toggle_mute:"))
async def toggle_mute_callback(callback: CallbackQuery):
    """Обробляє натискання на кнопки в меню налаштувань."""
    if not callback.from_user or not callback.data:
        return
        
    user_id = callback.from_user.id
    try:
        setting_key = callback.data.split(":")[1]
    except IndexError:
        logger.warning(f"Invalid callback data received: {callback.data}")
        await callback.answer("Помилка: Неправильні дані.", show_alert=True)
        return

    logger.info(f"User {user_id} toggling setting: '{setting_key}'")

    current_settings = await get_user_settings(user_id)
    field_name = f"mute_{setting_key}"
    
    if not hasattr(current_settings, field_name):
        logger.error(f"Attempt to toggle non-existent setting '{field_name}' by user {user_id}")
        await callback.answer("Помилка: Такого налаштування не існує.", show_alert=True)
        return
        
    new_value = not getattr(current_settings, field_name)
    
    success = await update_user_settings(user_id, **{field_name: new_value})
    
    if success:
        # Ми не використовуємо кеш для налаштувань, оскільки вони читаються напряму
        # await clear_user_cache(user_id) # Цей кеш для профілю, не для налаштувань
        await _show_or_update_settings_menu(callback)
    else:
        await callback.answer("Не вдалося зберегти налаштування. Спробуйте пізніше.", show_alert=True)


@settings_router.callback_query(F.data == "close_settings_menu")
async def close_settings_menu_callback(callback: CallbackQuery):
    """Обробляє закриття меню налаштувань."""
    if not callback.message:
        return
    try:
        await callback.message.delete()
        await callback.answer("Налаштування збережено.")
    except TelegramBadRequest:
        await callback.answer("Не вдалося закрити меню. Можливо, воно вже закрите.")
    except Exception as e:
        logger.error(f"Error closing settings menu for user {callback.from_user.id}: {e}")
        await callback.answer("Сталася помилка при закритті меню.")


def register_settings_handlers(dp: Router):
    """Реєструє обробники налаштувань."""
    dp.include_router(settings_router)
    logger.info("✅ Обробники налаштувань користувача (/mute, /settings) зареєстровано.")
