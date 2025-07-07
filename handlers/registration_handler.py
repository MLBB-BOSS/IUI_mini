#handlers/registration_handler.py
"""
Обробники для процесу реєстрації та управління профілем користувача
з реалізацією логіки "Чистого чату" та стійким збереженням файлів.
"""
import html
import base64
import io
from typing import Dict, Any, Optional, List
import asyncio

from aiogram import Bot, F, Router, types, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize, InputMediaPhoto, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from enum import Enum, auto
from aiohttp.client_exceptions import ClientResponseError

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import (
    create_expanded_profile_menu_keyboard,
    create_delete_confirm_keyboard
)
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id, delete_user_by_telegram_id
from config import OPENAI_API_KEY, logger
from utils.file_manager import file_resilience_manager

registration_router = Router()

# === ЛОГІКА КАРУСЕЛІ (зміни для використання permanent_url) ===

class CarouselType(Enum):
    AVATAR = auto()
    PROFILE = auto()
    STATS = auto()
    HEROES = auto()

CAROUSEL_TYPE_TO_KEY = {
    CarouselType.AVATAR: "custom_avatar_file_id",
    CarouselType.PROFILE: "profile_screenshot_file_id",
    CarouselType.STATS: "stats_screenshot_file_id",
    CarouselType.HEROES: "heroes_screenshot_file_id",
}

CAROUSEL_TYPE_TO_PERMANENT_KEY = {
    CarouselType.AVATAR: "custom_avatar_permanent_url",
    CarouselType.PROFILE: "profile_screenshot_permanent_url",
    CarouselType.STATS: "stats_screenshot_permanent_url",
    CarouselType.HEROES: "heroes_screenshot_permanent_url",
}

CAROUSEL_TYPE_TO_TITLE = {
    CarouselType.AVATAR: "🎭 Аватар",
    CarouselType.PROFILE: "👤 Основний профіль",
    CarouselType.STATS: "📊 Статистика",
    CarouselType.HEROES: "🦸 Улюблені герої",
}

DEFAULT_IMAGE_URL = "https://res.cloudinary.com/ha1pzppgf/image/upload/v1748286434/file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"

def create_carousel_keyboard(current_type: CarouselType, available_types: list[CarouselType]):
    builder = InlineKeyboardBuilder()
    current_idx = available_types.index(current_type)
    nav_row = [
        InlineKeyboardButton(text="◀️", callback_data=f"carousel:goto:{available_types[current_idx - 1].name}") if current_idx > 0 else InlineKeyboardButton(text="•", callback_data="carousel:noop"),
        InlineKeyboardButton(text=f"{current_idx + 1}/{len(available_types)}", callback_data="carousel:noop"),
        InlineKeyboardButton(text="▶️", callback_data=f"carousel:goto:{available_types[current_idx + 1].name}") if current_idx < len(available_types) - 1 else InlineKeyboardButton(text="•", callback_data="carousel:noop")
    ]
    builder.row(*nav_row)
    edit_map = { CarouselType.AVATAR: "profile_add_avatar", CarouselType.PROFILE: "profile_update_basic", CarouselType.STATS: "profile_add_stats", CarouselType.HEROES: "profile_add_heroes" }
    builder.row(
        InlineKeyboardButton(text="🔄 Оновити", callback_data=edit_map[current_type]),
        InlineKeyboardButton(text="⚙️ Опції", callback_data="profile_menu_expand")
    )
    builder.row(InlineKeyboardButton(text="🚪 Закрити", callback_data="profile_carousel_close"))
    return builder.as_markup()

def format_profile_info(user_data: Dict[str, Any]) -> str:
    nickname = html.escape(user_data.get('nickname', 'Невідомо'))
    player_id = user_data.get('player_id', 'N/A')
    server_id = user_data.get('server_id', 'N/A')
    rank = html.escape(user_data.get('current_rank', 'Невідомо'))
    win_rate = user_data.get('win_rate')
    win_rate_str = f"{win_rate}%" if win_rate is not None else "N/A"
    matches = user_data.get('total_matches', 'N/A')
    heroes = html.escape(user_data.get('favorite_heroes', 'Не вказано'))
    return (f"👤 <b>{nickname}</b> | 🆔 {player_id}({server_id})\n"
            f"🏆 {rank} | 📊 {win_rate_str} ({matches} матчів)\n"
            f"🦸 <b>Герої:</b> {heroes}")

def get_caption_for_carousel_type(carousel_type: CarouselType, user_data: Dict[str, Any]) -> str:
    title = CAROUSEL_TYPE_TO_TITLE.get(carousel_type, "Профіль")
    if carousel_type == CarouselType.AVATAR:
        return f"<b>{title}</b>\n\n{format_profile_info(user_data)}"
    return f"<b>{title}</b>"

async def show_profile_carousel(bot: Bot, chat_id: int, user_id: int, carousel_type: CarouselType = CarouselType.AVATAR, message_to_edit: Optional[Message] = None):
    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        text = "Профіль не знайдено. Будь ласка, пройдіть реєстрацію з /profile."
        if message_to_edit and not message_to_edit.photo:
            await message_to_edit.edit_text(text)
        else:
            if message_to_edit: await message_to_edit.delete()
            await bot.send_message(chat_id, text)
        return

    available_types = [c for c in CarouselType if user_data.get(CAROUSEL_TYPE_TO_PERMANENT_KEY.get(c)) or user_data.get(CAROUSEL_TYPE_TO_KEY.get(c))]
    if not available_types: available_types.append(CarouselType.AVATAR)
    if carousel_type not in available_types: carousel_type = available_types[0]

    permanent_url = user_data.get(CAROUSEL_TYPE_TO_PERMANENT_KEY.get(carousel_type))
    temp_file_id = user_data.get(CAROUSEL_TYPE_TO_KEY.get(carousel_type))
    
    media_source = permanent_url or temp_file_id or DEFAULT_IMAGE_URL
    
    keyboard = create_carousel_keyboard(carousel_type, available_types)
    caption = get_caption_for_carousel_type(carousel_type, user_data)
    media = InputMediaPhoto(media=media_source, caption=caption)

    try:
        if message_to_edit:
            if message_to_edit.photo:
                await bot.edit_message_media(chat_id, message_to_edit.message_id, media, reply_markup=keyboard)
            else:
                await message_to_edit.delete()
                await bot.send_photo(chat_id, media_source, caption=caption, reply_markup=keyboard)
        else:
            await bot.send_photo(chat_id, media_source, caption=caption, reply_markup=keyboard)
    except TelegramAPIError as e:
        logger.error(f"Помилка показу/оновлення каруселі: {e}. Спроба відправити заново.")
        if "message to edit not found" in str(e).lower():
             await bot.send_photo(chat_id, media_source, caption=caption, reply_markup=keyboard)
        else:
            fallback_source = temp_file_id if media_source == permanent_url else permanent_url
            if fallback_source:
                 try:
                    await bot.send_photo(chat_id, fallback_source, caption=caption, reply_markup=keyboard)
                    return
                 except TelegramAPIError:
                    pass
            await bot.send_message(chat_id, "Не вдалося оновити профіль. Спробуйте ще раз.")

# === ОСНОВНІ ОБРОБНИКИ ===
@registration_router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext, bot: Bot):
    if not message.from_user: return
    await state.clear()
    try: await message.delete()
    except TelegramAPIError: pass
    user_data = await get_user_by_telegram_id(message.from_user.id)
    if user_data:
        await show_profile_carousel(bot, message.chat.id, message.from_user.id)
    else:
        await state.set_state(RegistrationFSM.waiting_for_basic_photo)
        sent_msg = await bot.send_message(message.chat.id, "👋 Вітаю! Схоже, ви тут уперше.\n\nДля створення профілю, надішліть скріншот вашого ігрового профілю.")
        await state.update_data(last_bot_message_id=sent_msg.message_id)

# === ✅✅✅ ГОЛОВНИЙ ОНОВЛЕНИЙ ОБРОБНИК FSM ДЛЯ ФОТО (З ВИПРАВЛЕННЯМ) ✅✅✅ ===
@registration_router.message(StateFilter(RegistrationFSM.waiting_for_basic_photo, RegistrationFSM.waiting_for_stats_photo, RegistrationFSM.waiting_for_heroes_photo, RegistrationFSM.waiting_for_avatar_photo), F.photo)
async def fsm_photo_handler(message: Message, state: FSMContext, bot: Bot):
    if not (message.photo and message.from_user): return
    
    user_id = message.from_user.id
    state_data = await state.get_data()
    last_bot_msg_id = state_data.get("last_bot_message_id")
    current_state_str = await state.get_state()
    
    thinking_msg = await bot.send_message(message.chat.id, "Обробляю ваше зображення... 🤖")

    try:
        largest_photo = max(message.photo, key=lambda p: p.file_size or 0)
        
        # ✅ КРОК 1: СПОЧАТКУ завантажуємо байти зображення з Telegram
        image_bytes_io = await bot.download_file(largest_photo.file_id)
        if not image_bytes_io:
            await thinking_msg.edit_text("❌ Не вдалося завантажити файл з серверів Telegram.")
            return
            
        # ✅ КРОК 2: ТЕПЕР безпечно видаляємо повідомлення, бо файл вже у нас
        try:
            await message.delete()
            if last_bot_msg_id:
                await bot.delete_message(message.chat.id, last_bot_msg_id)
        except TelegramAPIError:
            logger.warning("Не вдалося видалити вихідні повідомлення, але файл вже завантажено.")
            pass

        image_bytes = image_bytes_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        update_data = {'telegram_id': user_id}
        
        mode_map = {
            RegistrationFSM.waiting_for_basic_photo.state: ('basic', 'profile_screenshot'),
            RegistrationFSM.waiting_for_stats_photo.state: ('stats', 'stats_screenshot'),
            RegistrationFSM.waiting_for_heroes_photo.state: ('heroes', 'heroes_screenshot'),
            RegistrationFSM.waiting_for_avatar_photo.state: ('avatar', 'custom_avatar'),
        }
        analysis_mode, file_type_prefix = mode_map[current_state_str]

        # ✅ КРОК 3: Паралельно аналізуємо (OpenAI) і зберігаємо (Cloudinary)
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt, file_resilience_manager:
            if analysis_mode == 'avatar':
                analysis_result = {}
                permanent_url = await file_resilience_manager.optimize_and_store_image(image_bytes, user_id, file_type_prefix)
            else:
                analysis_task = gpt.analyze_user_profile(image_base64, mode=analysis_mode)
                storage_task = file_resilience_manager.optimize_and_store_image(image_bytes, user_id, file_type_prefix)
                analysis_result, permanent_url = await asyncio.gather(analysis_task, storage_task)

        # ✅ КРОК 4: Обробляємо результати
        if not permanent_url:
            await thinking_msg.edit_text("❌ Помилка збереження зображення. Спробуйте ще раз.")
            return

        if analysis_mode != 'avatar' and (not analysis_result or 'error' in analysis_result):
            error_msg = analysis_result.get('error', 'Не вдалося розпізнати дані.')
            await thinking_msg.edit_text(f"❌ Помилка аналізу: {error_msg}")
            return
        
        if analysis_mode == 'basic':
            update_data.update({
                'nickname': analysis_result.get('game_nickname'), 
                'player_id': int(str(analysis_result.get('mlbb_id_server', '0 (0)')).split(' ')[0]), 
                'server_id': int(str(analysis_result.get('mlbb_id_server', '0 (0)')).split('(')[1].replace(')', '')), 
                'current_rank': analysis_result.get('highest_rank_season'), 
                'total_matches': analysis_result.get('matches_played')
            })
        elif analysis_mode == 'stats':
            main_ind = analysis_result.get('main_indicators', {})
            update_data.update({'total_matches': main_ind.get('matches_played'), 'win_rate': main_ind.get('win_rate')})
        elif analysis_mode == 'heroes':
            heroes_list = analysis_result.get('favorite_heroes', [])
            update_data['favorite_heroes'] = ", ".join([h.get('hero_name', '') for h in heroes_list if h.get('hero_name')])

        update_data[f'{file_type_prefix}_file_id'] = largest_photo.file_id
        update_data[f'{file_type_prefix}_permanent_url'] = permanent_url
        
        # ✅ КРОК 5: Зберігаємо всі дані в БД
        status = await add_or_update_user({k: v for k, v in update_data.items() if v is not None})
        
        if status == 'success':
            await show_profile_carousel(bot, message.chat.id, user_id, message_to_edit=thinking_msg)
        elif status == 'conflict':
            await thinking_msg.edit_text("🛡️ <b>Конфлікт!</b> Цей ігровий профіль (Player ID) вже зареєстрований іншим користувачем.")
        else:
            await thinking_msg.edit_text("❌ Сталася невідома помилка під час збереження даних.")

    except ClientResponseError as e:
        if e.status == 404:
            logger.warning(f"Помилка завантаження файлу (404 Not Found): {e}. Ймовірно, повідомлення було видалено занадто швидко.")
            enhanced_error_msg = file_resilience_manager.get_enhanced_error_message(message.from_user.first_name if message.from_user else "друже")
            await thinking_msg.edit_text(enhanced_error_msg)
        else:
            logger.exception("Критична помилка обробки фото (ClientResponseError):")
            await thinking_msg.edit_text("Сталася неочікувана помилка при завантаженні. Спробуйте ще раз.")
    except Exception as e:
        logger.exception("Критична помилка обробки фото:")
        await thinking_msg.edit_text("Сталася неочікувана системна помилка.")
    finally:
        await state.clear()


def register_registration_handlers(dp: Dispatcher):
    dp.include_router(registration_router)
    logger.info("✅ Обробники реєстрації та профілю успішно зареєстровано.")
