"""
Обробники для відображення профілю користувача у форматі каруселі.
Реалізує інтерактивну навігацію між різними скріншотами профілю.
"""
import asyncio
from enum import Enum, auto
from typing import Dict, Any, Optional, List, Union, Tuple

from aiogram import Bot, Router, F, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

from database.crud import get_user_by_telegram_id
from config import logger
from keyboards.inline_keyboards import create_profile_menu_keyboard

# Створюємо новий роутер
profile_carousel_router = Router()

# Визначаємо константи для типів каруселі
class CarouselType(Enum):
    """Типи слайдів в каруселі профілю."""
    AVATAR = auto()  # Кастомний аватар (початковий слайд)
    PROFILE = auto()  # Скріншот основного профілю
    STATS = auto()    # Скріншот статистики
    HEROES = auto()   # Скріншот улюблених героїв

# Маппінг типів каруселі на ключі в даних користувача
CAROUSEL_TYPE_TO_KEY = {
    CarouselType.AVATAR: "custom_avatar_file_id",
    CarouselType.PROFILE: "profile_screenshot_file_id",
    CarouselType.STATS: "stats_screenshot_file_id",
    CarouselType.HEROES: "heroes_screenshot_file_id",
}

# Заголовки для кожного типу слайду
CAROUSEL_TYPE_TO_TITLE = {
    CarouselType.AVATAR: "🎭 Аватар",
    CarouselType.PROFILE: "👤 Основний профіль",
    CarouselType.STATS: "📊 Статистика",
    CarouselType.HEROES: "🦸 Улюблені герої",
}

# Спеціальний placeholder для відсутнього зображення
DEFAULT_IMAGE_URL = "https://res.cloudinary.com/ha1pzppgf/image/upload/v1748286434/file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"

def create_carousel_keyboard(
    current_type: CarouselType,
    available_types: List[CarouselType]
) -> InlineKeyboardMarkup:
    """
    Створює клавіатуру для навігації каруселлю профілю.
    
    Args:
        current_type: Поточний тип слайду.
        available_types: Список доступних типів слайдів.
        
    Returns:
        Клавіатура з кнопками навігації.
    """
    builder = InlineKeyboardBuilder()
    
    # Отримуємо індекс поточного типу в списку доступних
    current_idx = available_types.index(current_type)
    
    # Додаємо кнопки навігації ліворуч/праворуч, якщо є куди переходити
    nav_row = []
    
    if current_idx > 0:  # Якщо не перший слайд, додаємо кнопку "назад"
        prev_type = available_types[current_idx - 1]
        nav_row.append(InlineKeyboardButton(
            text="◀️",
            callback_data=f"carousel:goto:{prev_type.name}"
        ))
    else:
        # Placeholder для вирівнювання
        nav_row.append(InlineKeyboardButton(
            text="•",
            callback_data="carousel:noop"
        ))
    
    # Індикатор позиції
    position_text = f"{current_idx + 1}/{len(available_types)}"
    nav_row.append(InlineKeyboardButton(
        text=position_text,
        callback_data="carousel:noop"
    ))
    
    if current_idx < len(available_types) - 1:  # Якщо не останній слайд, додаємо кнопку "вперед"
        next_type = available_types[current_idx + 1]
        nav_row.append(InlineKeyboardButton(
            text="▶️",
            callback_data=f"carousel:goto:{next_type.name}"
        ))
    else:
        # Placeholder для вирівнювання
        nav_row.append(InlineKeyboardButton(
            text="•",
            callback_data="carousel:noop"
        ))
        
    builder.row(*nav_row)
    
    # Додаємо кнопку для редагування поточного типу слайду
    edit_callback_map = {
        CarouselType.AVATAR: "profile_add_avatar",
        CarouselType.PROFILE: "profile_update_basic",
        CarouselType.STATS: "profile_add_stats",
        CarouselType.HEROES: "profile_add_heroes",
    }
    
    builder.row(
        InlineKeyboardButton(
            text="🔄 Оновити",
            callback_data=edit_callback_map[current_type]
        ),
        InlineKeyboardButton(
            text="⚙️ Налаштування",
            callback_data="profile_menu_expand"
        )
    )
    
    # Додаємо кнопку виходу
    builder.row(
        InlineKeyboardButton(
            text="🚪 Закрити",
            callback_data="profile_carousel_close"
        )
    )
    
    return builder.as_markup()

def format_profile_info(user_data: Dict[str, Any]) -> str:
    """
    Форматує основну інформацію профілю для відображення під зображенням.
    
    Args:
        user_data: Дані користувача з бази даних.
        
    Returns:
        Відформатований текст з інформацією профілю.
    """
    nickname = user_data.get('nickname', 'Невідомо')
    player_id = user_data.get('player_id', 'Невідомо')
    server_id = user_data.get('server_id', 'Невідомо')
    rank = user_data.get('current_rank', 'Невідомо')
    win_rate = user_data.get('win_rate', 'Невідомо')
    win_rate_str = f"{win_rate}%" if win_rate is not None else "Невідомо"
    matches = user_data.get('total_matches', 'Невідомо')
    heroes = user_data.get('favorite_heroes', 'Не вказано')
    
    return (
        f"👤 <b>{nickname}</b>\n"
        f"🆔 <b>ID:</b> {player_id} ({server_id})\n"
        f"🏆 <b>Ранг:</b> {rank}\n"
        f"📊 <b>WR:</b> {win_rate_str} ({matches} матчів)\n"
        f"🦸 <b>Герої:</b> {heroes}"
    )

def get_caption_for_carousel_type(
    carousel_type: CarouselType,
    user_data: Dict[str, Any]
) -> str:
    """
    Генерує підпис для поточного слайду каруселі.
    
    Args:
        carousel_type: Тип слайду каруселі.
        user_data: Дані користувача з бази даних.
        
    Returns:
        Підпис для слайду каруселі.
    """
    title = CAROUSEL_TYPE_TO_TITLE.get(carousel_type, "Профіль")
    
    # Базова інформація профілю завжди відображається на аватарці
    if carousel_type == CarouselType.AVATAR:
        return f"<b>{title}</b>\n\n{format_profile_info(user_data)}"
    
    # Для інших типів - простіший підпис
    return f"<b>{title}</b>"

async def show_profile_carousel(
    bot: Bot,
    chat_id: int,
    user_id: int,
    carousel_type: CarouselType = CarouselType.AVATAR,
    message_to_edit: Optional[Message] = None,
) -> Union[Message, bool]:
    """
    Відображає або оновлює слайд каруселі профілю.
    
    Args:
        bot: Екземпляр бота.
        chat_id: ID чату для відправки повідомлення.
        user_id: ID користувача, чий профіль відображається.
        carousel_type: Тип слайду для відображення.
        message_to_edit: Повідомлення для редагування (якщо це оновлення).
        
    Returns:
        Нове повідомлення або True, якщо повідомлення успішно оновлено.
    """
    # Отримуємо дані користувача
    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        if message_to_edit:
            await message_to_edit.edit_text("Профіль не знайдено. Спробуйте /profile для реєстрації.")
        else:
            return await bot.send_message(chat_id, "Профіль не знайдено. Спробуйте /profile для реєстрації.")
        return False
    
    # Визначаємо, які типи слайдів доступні
    available_types = []
    for c_type in CarouselType:
        key = CAROUSEL_TYPE_TO_KEY.get(c_type)
        if key and user_data.get(key):
            available_types.append(c_type)
    
    # Якщо немає жодного зображення, додаємо хоча б аватар з плейсхолдером
    if not available_types:
        available_types = [CarouselType.AVATAR]
    
    # Якщо запитаного типу немає серед доступних, вибираємо перший доступний
    if carousel_type not in available_types:
        carousel_type = available_types[0]
    
    # Отримуємо file_id для поточного типу
    file_id_key = CAROUSEL_TYPE_TO_KEY.get(carousel_type)
    file_id = user_data.get(file_id_key) if file_id_key else None
    
    # Якщо файл відсутній, використовуємо заглушку
    if not file_id:
        file_id = DEFAULT_IMAGE_URL
    
    # Створюємо клавіатуру для навігації
    keyboard = create_carousel_keyboard(carousel_type, available_types)
    
    # Генеруємо підпис
    caption = get_caption_for_carousel_type(carousel_type, user_data)
    
    try:
        if message_to_edit:
            # Редагуємо існуюче повідомлення
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_to_edit.message_id,
                media=InputMediaPhoto(
                    media=file_id,
                    caption=caption,
                    parse_mode="HTML"
                ),
                reply_markup=keyboard
            )
            return True
        else:
            # Відправляємо нове повідомлення
            return await bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except TelegramAPIError as e:
        logger.error(f"Помилка відображення каруселі: {e}")
        if message_to_edit:
            await message_to_edit.edit_text(
                "Не вдалося відобразити зображення профілю. Спробуйте оновити профіль."
            )
        else:
            return await bot.send_message(
                chat_id, 
                "Не вдалося відобразити зображення профілю. Спробуйте оновити профіль."
            )
        return False

@profile_carousel_router.message(Command("profile"))
async def cmd_profile_carousel(message: Message, bot: Bot):
    """
    Обробник команди /profile з відображенням каруселі.
    Відповідає за показ профілю користувача в форматі каруселі.
    """
    if not message.from_user:
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        # Спочатку видаляємо команду для чистоти чату
        await message.delete()
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити команду /profile: {e}")
    
    # Перевіряємо, чи є користувач в базі даних
    user_data = await get_user_by_telegram_id(user_id)
    
    if not user_data:
        # Якщо користувач не знайдений, відправляємо на реєстрацію
        sent_message = await bot.send_message(
            chat_id,
            "👋 Вітаю! Схоже, ви тут уперше.\n\n"
            "Для створення профілю, будь ласка, надішліть мені скріншот "
            "вашого ігрового профілю (головна сторінка). 📸"
        )
        
        # Логіка для реєстрації буде виконуватися в registration_handler
        # Нам не потрібно нічого робити, просто повідомляємо користувача
    else:
        # Якщо користувач знайдений, показуємо карусель
        await show_profile_carousel(bot, chat_id, user_id)

@profile_carousel_router.callback_query(F.data.startswith("carousel:goto:"))
async def carousel_navigation(callback: CallbackQuery, bot: Bot):
    """
    Обробник кнопок навігації каруселі профілю.
    Відповідає за перемикання між різними типами слайдів.
    """
    if not callback.message or not callback.from_user:
        await callback.answer("Помилка: повідомлення не знайдено")
        return
    
    # Витягуємо тип каруселі з callback_data
    carousel_type_name = callback.data.split(":")[-1]
    try:
        carousel_type = CarouselType[carousel_type_name]
    except (KeyError, ValueError):
        await callback.answer("Помилка: невідомий тип слайду")
        return
    
    # Оновлюємо карусель
    result = await show_profile_carousel(
        bot,
        callback.message.chat.id,
        callback.from_user.id,
        carousel_type,
        callback.message
    )
    
    if result:
        await callback.answer()
    else:
        await callback.answer("Не вдалося відобразити цей тип слайду")

@profile_carousel_router.callback_query(F.data == "profile_carousel_close")
async def close_profile_carousel(callback: CallbackQuery):
    """
    Обробник кнопки закриття каруселі профілю.
    """
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено")
        return
    
    try:
        await callback.message.delete()
        await callback.answer("Меню закрито")
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення каруселі: {e}")
        await callback.answer("Не вдалося закрити меню", show_alert=True)

@profile_carousel_router.callback_query(F.data == "carousel:noop")
async def carousel_noop(callback: CallbackQuery):
    """
    Обробник "пустих" кнопок каруселі (індикатори, заглушки).
    """
    await callback.answer()

def register_profile_carousel_handlers(dp: Dispatcher):
    """
    Реєструє всі обробники, пов'язані з каруселлю профілю.
    """
    dp.include_router(profile_carousel_router)
    logger.info("✅ Обробники для каруселі профілю успішно зареєстровано.")
