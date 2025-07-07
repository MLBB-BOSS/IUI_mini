#handlers/registration_handler.py
"""
Обробники для процесу реєстрації та управління профілем користувача
з реалізацією логіки "Чистого чату".
"""
import html
import base64
import io
from typing import Dict, Any, Optional
import asyncio

from aiogram import Bot, F, Router, types, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize, InputMediaPhoto, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from enum import Enum, auto

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import (
    create_expanded_profile_menu_keyboard,
    create_delete_confirm_keyboard
)
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id, delete_user_by_telegram_id
from config import OPENAI_API_KEY, logger

registration_router = Router()

# === ЛОГІКА КАРУСЕЛІ (ПЕРЕНЕСЕНО З ВИДАЛЕНОГО PROFILE_HANDLER) ===

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

    available_types = [c for c in CarouselType if user_data.get(CAROUSEL_TYPE_TO_KEY.get(c))]
    if not available_types: available_types.append(CarouselType.AVATAR) # Завжди показуємо аватар
    if carousel_type not in available_types: carousel_type = available_types[0]

    file_id = user_data.get(CAROUSEL_TYPE_TO_KEY.get(carousel_type)) or DEFAULT_IMAGE_URL
    keyboard = create_carousel_keyboard(carousel_type, available_types)
    caption = get_caption_for_carousel_type(carousel_type, user_data)
    media = InputMediaPhoto(media=file_id, caption=caption)

    try:
        if message_to_edit:
            if message_to_edit.photo:
                await bot.edit_message_media(chat_id, message_to_edit.message_id, media, reply_markup=keyboard)
            else:
                await message_to_edit.delete()
                await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=keyboard)
        else:
            await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=keyboard)
    except TelegramAPIError as e:
        logger.error(f"Помилка показу/оновлення каруселі: {e}. Спроба відправити заново.")
        if "message to edit not found" in str(e):
             await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=keyboard)
        else:
            await bot.send_message(chat_id, "Не вдалося оновити профіль. Спробуйте ще раз.")

async def safe_edit_message(message: Optional[Message], new_text: str, reply_markup=None):
    if not message: return
    try:
        if message.photo:
            await message.edit_caption(caption=new_text, reply_markup=reply_markup)
        else:
            await message.edit_text(text=new_text, reply_markup=reply_markup)
    except TelegramAPIError as e:
        logger.error(f"Безпечне редагування не вдалося: {e}. Повідомлення ID: {message.message_id}")

# === ОСНОВНИЙ ОБРОБНИК КОМАНДИ /profile ===
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

# === ОБРОБНИКИ КНОПОК КАРУСЕЛІ ТА МЕНЮ ===
@registration_router.callback_query(F.data.startswith("carousel:goto:"))
async def carousel_navigation_handler(callback: CallbackQuery, bot: Bot):
    if not (callback.message and callback.from_user): return
    try:
        carousel_type = CarouselType[callback.data.split(":")[-1]]
        await show_profile_carousel(bot, callback.message.chat.id, callback.from_user.id, carousel_type, callback.message)
    except (KeyError, ValueError, TelegramAPIError) as e:
        logger.error(f"Помилка навігації каруселі: {e}")
        await callback.answer("Щось пішло не так з навігацією.", show_alert=True)
    finally:
        await callback.answer()

@registration_router.callback_query(F.data == "profile_carousel_close")
async def close_carousel_handler(callback: CallbackQuery):
    if callback.message: await callback.message.delete()
    await callback.answer("Меню закрито.")

@registration_router.callback_query(F.data == "carousel:noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()

@registration_router.callback_query(F.data == "profile_menu_expand")
async def expand_menu_handler(callback: CallbackQuery):
    if callback.message:
        await safe_edit_message(callback.message, callback.message.caption, create_expanded_profile_menu_keyboard())
    await callback.answer()

# === FSM ДЛЯ ОНОВЛЕННЯ ПРОФІЛЮ ===
# ... (решта коду залишається без змін, але я його повністю переглянув і додав виправлення)

@registration_router.callback_query(F.data.in_({"profile_update_basic", "profile_add_stats", "profile_add_heroes", "profile_add_avatar"}))
async def profile_update_fsm_start(callback: CallbackQuery, state: FSMContext):
    state_map = {
        "profile_update_basic": (RegistrationFSM.waiting_for_basic_photo, "Надішліть скріншот основного профілю."),
        "profile_add_stats": (RegistrationFSM.waiting_for_stats_photo, "Надішліть скріншот статистики."),
        "profile_add_heroes": (RegistrationFSM.waiting_for_heroes_photo, "Надішліть скріншот улюблених героїв."),
        "profile_add_avatar": (RegistrationFSM.waiting_for_avatar_photo, "Надішліть зображення для аватара."),
    }
    new_state, text = state_map[callback.data]
    await state.set_state(new_state)
    if callback.message:
        await safe_edit_message(callback.message, text)
        await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()

@registration_router.message(StateFilter(RegistrationFSM.waiting_for_basic_photo, RegistrationFSM.waiting_for_stats_photo, RegistrationFSM.waiting_for_heroes_photo, RegistrationFSM.waiting_for_avatar_photo), F.photo)
async def fsm_photo_handler(message: Message, state: FSMContext, bot: Bot):
    if not (message.photo and message.from_user): return
    
    state_data = await state.get_data()
    last_bot_msg_id = state_data.get("last_bot_message_id")
    current_state_str = await state.get_state()
    
    try: await message.delete()
    except TelegramAPIError: pass

    if not last_bot_msg_id:
        await bot.send_message(message.chat.id, "Помилка стану. Почніть з /profile.")
        await state.clear()
        return

    thinking_msg = await bot.send_message(message.chat.id, "Обробляю ваше зображення... 🤖")
    if last_bot_msg_id:
        try: await bot.delete_message(message.chat.id, last_bot_msg_id)
        except TelegramAPIError: pass

    try:
        largest_photo = max(message.photo, key=lambda p: p.file_size or 0)
        update_data = {'telegram_id': message.from_user.id}
        
        mode_map = {
            RegistrationFSM.waiting_for_basic_photo.state: ('basic', 'profile_screenshot_file_id'),
            RegistrationFSM.waiting_for_stats_photo.state: ('stats', 'stats_screenshot_file_id'),
            RegistrationFSM.waiting_for_heroes_photo.state: ('heroes', 'heroes_screenshot_file_id'),
        }

        if current_state_str == RegistrationFSM.waiting_for_avatar_photo.state:
            update_data['custom_avatar_file_id'] = largest_photo.file_id
        else:
            analysis_mode, file_id_key = mode_map[current_state_str]
            image_bytes_io = await bot.download_file(largest_photo.file_id)
            image_base64 = base64.b64encode(image_bytes_io.read()).decode('utf-8')
            
            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                analysis_result = await gpt.analyze_user_profile(image_base64, mode=analysis_mode)

            if not analysis_result or 'error' in analysis_result:
                error_msg = analysis_result.get('error', 'Не вдалося розпізнати дані.')
                await thinking_msg.edit_text(f"❌ Помилка: {error_msg}")
                return

            if analysis_mode == 'basic':
                update_data.update({
                    'nickname': analysis_result.get('game_nickname'), 
                    'player_id': int(analysis_result.get('mlbb_id_server', '0 (0)').split(' ')[0]), 
                    'server_id': int(analysis_result.get('mlbb_id_server', '0 (0)').split('(')[1].replace(')', '')), 
                    'current_rank': analysis_result.get('highest_rank_season'), 
                    'total_matches': analysis_result.get('matches_played')
                })
            elif analysis_mode == 'stats':
                main_ind = analysis_result.get('main_indicators', {})
                update_data.update({'total_matches': main_ind.get('matches_played'), 'win_rate': main_ind.get('win_rate')})
            elif analysis_mode == 'heroes':
                heroes_list = analysis_result.get('favorite_heroes', [])
                update_data['favorite_heroes'] = ", ".join([h.get('hero_name', '') for h in heroes_list if h.get('hero_name')])
            
            update_data[file_id_key] = largest_photo.file_id
        
        status = await add_or_update_user({k: v for k, v in update_data.items() if v is not None})
        
        if status == 'success':
            await show_profile_carousel(bot, message.chat.id, message.from_user.id, message_to_edit=thinking_msg)
        elif status == 'conflict':
            await thinking_msg.edit_text("🛡️ <b>Конфлікт!</b> Цей профіль вже зареєстрований.")
        else:
            await thinking_msg.edit_text("❌ Помилка збереження даних.")
    except Exception as e:
        logger.exception("Критична помилка обробки фото:")
        await thinking_msg.edit_text("Сталася неочікувана помилка.")
    finally:
        await state.clear()


# === ОБРОБНИКИ ВИДАЛЕННЯ ===
@registration_router.callback_query(F.data == "profile_delete")
async def delete_profile_start(callback: CallbackQuery, state: FSMContext):
    if callback.message:
        await state.set_state(RegistrationFSM.confirming_deletion)
        await safe_edit_message(
            callback.message, 
            "Ви впевнені, що хочете видалити профіль? Ця дія невідворотна.",
            create_delete_confirm_keyboard()
        )
    await callback.answer()

@registration_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_yes")
async def delete_profile_confirm(callback: CallbackQuery, state: FSMContext):
    if not (callback.from_user and callback.message): return
    deleted = await delete_user_by_telegram_id(callback.from_user.id)
    await safe_edit_message(callback.message, "Ваш профіль було успішно видалено." if deleted else "Не вдалося видалити профіль.")
    await state.clear()
    await callback.answer("Профіль видалено." if deleted else "Помилка видалення.", show_alert=True)

@registration_router.callback_query(RegistrationFSM.confirming_deletion, F.data == "delete_confirm_no")
async def delete_profile_cancel(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not (callback.from_user and callback.message): return
    await state.clear()
    await show_profile_carousel(bot, callback.message.chat.id, callback.from_user.id, message_to_edit=callback.message)
    await callback.answer("Дію скасовано.")

def register_registration_handlers(dp: Dispatcher):
    dp.include_router(registration_router)
    logger.info("✅ Обробники реєстрації та профілю успішно зареєстровано.")
