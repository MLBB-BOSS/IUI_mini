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
from keyboards.inline_keyboards import create_profile_menu_keyboard, create_expanded_profile_menu_keyboard

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
    """
    builder = InlineKeyboardBuilder()
    current_idx = available_types.index(current_type)
    
    nav_row = []
    if current_idx > 0:
        prev_type = available_types[current_idx - 1]
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"carousel:goto:{prev_type.name}"))
    else:
        nav_row.append(InlineKeyboardButton(text="•", callback_data="carousel:noop"))
    
    position_text = f"{current_idx + 1}/{len(available_types)}"
    nav_row.append(InlineKeyboardButton(text=position_text, callback_data="carousel:noop"))
    
    if current_idx < len(available_types) - 1:
        next_type = available_types[current_idx + 1]
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"carousel:goto:{next_type.name}"))
    else:
        nav_row.append(InlineKeyboardButton(text="•", callback_data="carousel:noop"))
        
    builder.row(*nav_row)
    
    edit_callback_map = {
        CarouselType.AVATAR: "profile_add_avatar",
        CarouselType.PROFILE: "profile_update_basic",
        CarouselType.STATS: "profile_add_stats",
        CarouselType.HEROES: "profile_add_heroes",
    }
    
    builder.row(
        InlineKeyboardButton(text="🔄 Оновити це фото", callback_data=edit_callback_map[current_type]),
        InlineKeyboardButton(text="⚙️ Більше опцій", callback_data="profile_menu_expand")
    )
    
    builder.row(InlineKeyboardButton(text="🚪 Закрити", callback_data="profile_carousel_close"))
    
    return builder.as_markup()

def format_profile_info(user_data: Dict[str, Any]) -> str:
    """Форматує основну інформацію профілю."""
    nickname = user_data.get('nickname', 'Невідомо')
    player_id = user_data.get('player_id', 'Невідомо')
    server_id = user_data.get('server_id', 'Невідомо')
    rank = user_data.get('current_rank', 'Невідомо')
    win_rate = user_data.get('win_rate')
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
    """Генерує підпис для слайду."""
    title = CAROUSEL_TYPE_TO_TITLE.get(carousel_type, "Профіль")
    if carousel_type == CarouselType.AVATAR:
        return f"<b>{title}</b>\n\n{format_profile_info(user_data)}"
    return f"<b>{title}</b>"

async def show_profile_carousel(
    bot: Bot,
    chat_id: int,
    user_id: int,
    carousel_type: CarouselType = CarouselType.AVATAR,
    message_to_edit: Optional[Message] = None,
) -> Union[Message, bool]:
    """Відображає або оновлює слайд каруселі профілю."""
    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        text = "Профіль не знайдено. Спробуйте /profile для реєстрації."
        if message_to_edit:
            await message_to_edit.edit_text(text)
        else:
            return await bot.send_message(chat_id, text)
        return False
    
    available_types = [c_type for c_type in CarouselType if CAROUSEL_TYPE_TO_KEY.get(c_type) and user_data.get(CAROUSEL_TYPE_TO_KEY[c_type])]
    if not available_types:
        available_types = [CarouselType.AVATAR]
    
    if carousel_type not in available_types:
        carousel_type = available_types[0]
    
    file_id_key = CAROUSEL_TYPE_TO_KEY.get(carousel_type)
    file_id = user_data.get(file_id_key) if file_id_key else None
    if not file_id:
        file_id = DEFAULT_IMAGE_URL
    
    keyboard = create_carousel_keyboard(carousel_type, available_types)
    caption = get_caption_for_carousel_type(carousel_type, user_data)
    
    media = InputMediaPhoto(media=file_id, caption=caption, parse_mode="HTML")
    
    try:
        # ✅ ВИПРАВЛЕНО: обробка редагування текстового повідомлення
        if message_to_edit:
            # Якщо вихідне повідомлення - фото, редагуємо медіа
            if message_to_edit.photo:
                await bot.edit_message_media(
                    chat_id=chat_id, message_id=message_to_edit.message_id,
                    media=media, reply_markup=keyboard
                )
            else: # Якщо вихідне повідомлення - текст, видаляємо його і надсилаємо фото
                await message_to_edit.delete()
                await bot.send_photo(
                    chat_id=chat_id, photo=file_id, caption=caption,
                    reply_markup=keyboard, parse_mode="HTML"
                )
            return True
        else: # Відправляємо нове повідомлення
            return await bot.send_photo(
                chat_id=chat_id, photo=file_id, caption=caption,
                reply_markup=keyboard, parse_mode="HTML"
            )
    except TelegramAPIError as e:
        logger.error(f"Помилка відображення каруселі: {e}")
        error_text = "Не вдалося відобразити зображення профілю. Спробуйте оновити профіль."
        if message_to_edit:
            await message_to_edit.edit_text(error_text)
        else:
            return await bot.send_message(chat_id, error_text)
        return False

@profile_carousel_router.message(Command("profile"))
async def cmd_profile_carousel(message: Message, bot: Bot, state: FSMContext):
    """Обробник команди /profile з відображенням каруселі."""
    if not message.from_user: return
    
    await state.clear() # Очищуємо стан на випадок, якщо користувач був у іншому процесі
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    try:
        await message.delete()
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити команду /profile: {e}")
    
    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        await state.set_state(RegistrationFSM.waiting_for_basic_photo)
        sent_message = await bot.send_message(
            chat_id,
            "👋 Вітаю! Схоже, ви тут уперше.\n\n"
            "Для створення профілю, будь ласка, надішліть мені скріншот "
            "вашого ігрового профілю (головна сторінка). 📸"
        )
        await state.update_data(last_bot_message_id=sent_message.message_id)
    else:
        await show_profile_carousel(bot, chat_id, user_id)

@profile_carousel_router.callback_query(F.data.startswith("carousel:goto:"))
async def carousel_navigation(callback: CallbackQuery, bot: Bot):
    """Обробник кнопок навігації каруселі."""
    if not callback.message or not callback.from_user:
        return await callback.answer("Помилка: повідомлення не знайдено")
    
    try:
        carousel_type = CarouselType[callback.data.split(":")[-1]]
    except (KeyError, ValueError):
        return await callback.answer("Помилка: невідомий тип слайду")
    
    if await show_profile_carousel(bot, callback.message.chat.id, callback.from_user.id, carousel_type, callback.message):
        await callback.answer()
    else:
        await callback.answer("Не вдалося відобразити цей тип слайду")

@profile_carousel_router.callback_query(F.data == "profile_carousel_close")
async def close_profile_carousel(callback: CallbackQuery):
    """Обробник кнопки закриття каруселі."""
    if not callback.message: return await callback.answer("Помилка")
    try:
        await callback.message.delete()
        await callback.answer("Меню закрито")
    except TelegramAPIError:
        await callback.answer("Не вдалося закрити меню", show_alert=True)

@profile_carousel_router.callback_query(F.data == "carousel:noop")
async def carousel_noop(callback: CallbackQuery):
    """Обробник "пустих" кнопок."""
    await callback.answer()

@profile_carousel_router.callback_query(F.data == "profile_menu_expand")
async def expand_menu_from_carousel(callback: CallbackQuery):
    """Розгортає меню налаштувань з каруселі."""
    if not callback.message: return await callback.answer("Помилка")
    await callback.message.edit_reply_markup(reply_markup=create_expanded_profile_menu_keyboard())
    await callback.answer()

def register_profile_carousel_handlers(dp: Dispatcher):
    """Реєструє обробники для каруселі профілю."""
    dp.include_router(profile_carousel_router)
    logger.info("✅ Обробники для каруселі профілю успішно зареєстровано.")