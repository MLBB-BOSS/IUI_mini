"""
Обробники для меню налаштувань користувача.
Відповідає за відображення та оновлення індивідуальних налаштувань м'юту.
"""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError

from database.crud import get_user_settings, update_user_settings
from keyboards.inline_keyboards import create_mute_settings_keyboard
from config import logger

settings_router = Router()

@settings_router.message(Command("settings"))
async def show_settings_menu(message: types.Message):
    """
    Обробник команди /settings.
    Показує меню з індивідуальними налаштуваннями м'юту.
    """
    if not message.from_user:
        return

    user_id = message.from_user.id
    logger.info(f"User {user_id} requested settings menu.")
    
    settings = await get_user_settings(user_id)
    keyboard = create_mute_settings_keyboard(settings)
    
    await message.answer(
        "⚙️ <b>Налаштування моїх реакцій</b>\n\n"
        "Тут ти можеш вказати, на які типи повідомлень мені реагувати, а які ігнорувати.",
        reply_markup=keyboard
    )

@settings_router.callback_query(F.data.startswith("toggle_mute:"))
async def toggle_setting(callback: types.CallbackQuery):
    """
    Обробляє натискання на кнопку налаштування, перемикаючи її стан.
    """
    if not callback.message:
        return
        
    user_id = callback.from_user.id
    setting_to_toggle = callback.data.split(":")[1]
    
    logger.info(f"User {user_id} toggling setting: '{setting_to_toggle}'")

    current_settings = await get_user_settings(user_id)
    setting_key = f"mute_{setting_to_toggle}"
    
    if not hasattr(current_settings, setting_key):
        await callback.answer("Помилка: невідоме налаштування.", show_alert=True)
        return

    current_value = getattr(current_settings, setting_key)
    new_value = not current_value

    success = await update_user_settings(user_id, **{setting_key: new_value})

    if success:
        # Отримуємо свіжі налаштування для оновлення клавіатури
        updated_settings = await get_user_settings(user_id)
        keyboard = create_mute_settings_keyboard(updated_settings)
        try:
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            await callback.answer(f"Налаштування '{setting_to_toggle}' оновлено!")
        except TelegramAPIError as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"Error updating settings keyboard for {user_id}: {e}")
                await callback.answer("Помилка оновлення меню.")
            else:
                # Якщо повідомлення не змінилося, все одно відповідаємо на колбек
                await callback.answer()
    else:
        logger.error(f"Failed to update settings for user {user_id} in DB.")
        await callback.answer("Не вдалося зберегти налаштування. Спробуйте пізніше.", show_alert=True)

@settings_router.callback_query(F.data == "close_settings_menu")
async def close_settings_menu(callback: types.CallbackQuery):
    """
    Обробляє натискання на кнопку "Готово", видаляючи меню налаштувань.
    """
    try:
        await callback.message.delete()
        await callback.answer("Налаштування збережено!")
    except TelegramAPIError:
        await callback.answer("Не вдалося закрити меню.")

def register_settings_handlers(dp: Router):
    """Реєструє обробники налаштувань."""
    dp.include_router(settings_router)
    logger.info("✅ Обробники налаштувань користувача зареєстровано.")
