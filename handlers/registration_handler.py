"""
Обробники для процесу реєстрації та управління профілем користувача
з реалізацією логіки "чистого чату" та каруселі профілю.
"""
import html
import base64
import io
from typing import Any, Dict, List, Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    PhotoSize,
    InputMediaPhoto,
)
from aiogram.exceptions import TelegramAPIError

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import (
    create_profile_menu_keyboard,
    create_profile_menu_overview_keyboard,
    create_delete_confirm_keyboard,
)
from services.openai_service import MLBBChatGPT
from database.crud import (
    add_or_update_user,
    get_user_by_telegram_id,
    delete_user_by_telegram_id,
)
from utils.file_manager import file_resilience_manager
from config import OPENAI_API_KEY, logger

registration_router = Router()


def format_profile_display(user_data: Dict[str, Any]) -> str:
    """Форматує дані профілю для відображення користувачу."""
    nickname = html.escape(user_data.get("nickname", "Не вказано"))
    player_id = user_data.get("player_id", "N/A")
    server_id = user_data.get("server_id", "N/A")
    current_rank = html.escape(user_data.get("current_rank", "Не вказано"))
    total_matches = user_data.get("total_matches", "Не вказано")
    win_rate = user_data.get("win_rate")
    win_rate_str = f"{win_rate}%" if win_rate is not None else "Не вказано"
    heroes = user_data.get("favorite_heroes")
    heroes_str = html.escape(heroes) if heroes else "Не вказано"

    return (
        f"<b>Ваш профіль:</b>\n\n"
        f"👤 <b>Нікнейм:</b> {nickname}\n"
        f"🆔 <b>ID:</b> {player_id} ({server_id})\n"
        f"🏆 <b>Ранг:</b> {current_rank}\n"
        f"⚔️ <b>Матчів:</b> {total_matches}\n"
        f"📊 <b>WR:</b> {win_rate_str}\n"
        f"🦸 <b>Улюблені герої:</b> {heroes_str}"
    )


async def build_profile_pages(user_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Формує перелік сторінок профілю:
      [{'photo': url, 'caption': text}, ...]
    Порядок: basic → stats → heroes → avatar.
    """
    pages: List[Dict[str, str]] = []
    # Базова сторінка
    caption_basic = format_profile_display(user_data)
    url_basic = user_data.get("basic_profile_permanent_url")
    pages.append({"photo": url_basic or "", "caption": caption_basic})

    # Статистика
    url_stats = user_data.get("stats_photo_permanent_url")
    if url_stats:
        caption_stats = (
            f"<b>Статистика:</b>\n"
            f"⚔️ Матчів: {user_data.get('total_matches', 'N/A')}\n"
            f"📊 WR: {user_data.get('win_rate', 'N/A')}%"
        )
        pages.append({"photo": url_stats, "caption": caption_stats})

    # Герої
    url_heroes = user_data.get("heroes_photo_permanent_url")
    if url_heroes:
        caption_heroes = (
            f"<b>Улюблені герої:</b> "
            f"{html.escape(user_data.get('favorite_heroes', 'Не вказано'))}"
        )
        pages.append({"photo": url_heroes, "caption": caption_heroes})

    # Аватар
    url_avatar = user_data.get("avatar_permanent_url")
    if url_avatar:
        pages.append({"photo": url_avatar, "caption": "<b>Ваш аватар</b>"})

    return pages


async def show_profile_carousel(
    bot: Bot,
    chat_id: int,
    message_id: int,
    user_id: int,
    page_index: int,
):
    """
    Рендерить carousel: міняє фото+підпис і оновлює клавіатуру.
    """
    user_data = await get_user_by_telegram_id(user_id) or {}
    pages = await build_profile_pages(user_data)
    total = len(pages)
    page = pages[page_index]

    # Зміна медіа, якщо є фото
    if page["photo"]:
        media = InputMediaPhoto(media=page["photo"])
        await bot.edit_message_media(
            chat_id=chat_id, message_id=message_id, media=media
        )

    # Оновлення підпису та клавіатури
    await bot.edit_message_caption(
        chat_id=chat_id,
        message_id=message_id,
        caption=page["caption"],
        parse_mode="HTML",
        reply_markup=create_profile_menu_overview_keyboard(
            current_page=page_index + 1, total_pages=total
        ),
    )


async def show_profile_menu(
    bot: Bot,
    chat_id: int,
    user_id: int,
    message_to_delete_id: Optional[int] = None,
):
    """
    Відображає першу сторінку профілю в однокнопковому режимі.
    """
    if message_to_delete_id:
        try:
            await bot.delete_message(chat_id, message_to_delete_id)
        except TelegramAPIError as e:
            logger.warning(f"Не вдалося видалити повідомлення {message_to_delete_id}: {e}")

    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        await bot.send_message(
            chat_id,
            "Не вдалося знайти ваш профіль. Спробуйте почати з /profile.",
        )
        return

    url = user_data.get("basic_profile_permanent_url")
    caption = format_profile_display(user_data)
    if url:
        await bot.send_photo(
            chat_id,
            url,
            caption=caption,
            reply_markup=create_profile_menu_keyboard(),
            parse_mode="HTML",
        )
    else:
        await bot.send_message(
            chat_id,
            caption,
            reply_markup=create_profile_menu_keyboard(),
            parse_mode="HTML",
        )


@registration_router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext, bot: Bot):
    """Центральна команда для управління/реєстрації профілю."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    await state.clear()
    existing = await get_user_by_telegram_id(user_id)
    if existing:
        await show_profile_menu(bot, chat_id, user_id)
    else:
        await state.set_state(RegistrationFSM.waiting_for_basic_photo)
        sent = await bot.send_message(
            chat_id,
            "👋 Вітаю! Схоже, ви тут уперше.\n\n"
            "Надішліть скріншот вашого ігрового профілю для реєстрації. 📸",
        )
        await state.update_data(last_bot_message_id=sent.message_id)


# ---- Додані обробники для заміни edit_text на edit_caption у фото ----

@registration_router.callback_query(F.data == "profile_update_basic")
async def profile_update_basic_handler(callback: CallbackQuery, state: FSMContext):
    """Обробник оновлення базової картки профілю."""
    await state.set_state(RegistrationFSM.waiting_for_basic_photo)
    text = "Будь ласка, надішліть новий скріншот основної сторінки профілю."
    # Якщо це фото-повідомлення, міняємо caption, інакше – текст
    if callback.message.photo:
        await callback.message.edit_caption(text, parse_mode="HTML")
    else:
        await callback.message.edit_text(text)
    await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()


@registration_router.callback_query(F.data == "profile_update_stats")
async def profile_add_stats_handler(callback: CallbackQuery, state: FSMContext):
    """Обробник оновлення статистики профілю."""
    await state.set_state(RegistrationFSM.waiting_for_stats_photo)
    text = "Надішліть скріншот розділу 'Statistics' → 'All Seasons'."
    if callback.message.photo:
        await callback.message.edit_caption(text, parse_mode="HTML")
    else:
        await callback.message.edit_text(text)
    await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()


@registration_router.callback_query(F.data == "profile_update_heroes")
async def profile_add_heroes_handler(callback: CallbackQuery, state: FSMContext):
    """Обробник оновлення улюблених героїв профілю."""
    await state.set_state(RegistrationFSM.waiting_for_heroes_photo)
    text = "Надішліть скріншот розділу 'Favorite' → 'All Seasons' (топ-3)."
    if callback.message.photo:
        await callback.message.edit_caption(text, parse_mode="HTML")
    else:
        await callback.message.edit_text(text)
    await state.update_data(last_bot_message_id=callback.message.message_id)
    await callback.answer()


@registration_router.message(
    StateFilter(
        RegistrationFSM.waiting_for_basic_photo,
        RegistrationFSM.waiting_for_stats_photo,
        RegistrationFSM.waiting_for_heroes_photo,
    ),
    F.photo,
)
async def handle_profile_update_photo(
    message: Message, state: FSMContext, bot: Bot
):
    """
    Універсальний обробник фото у станах контролю реєстрації.
    Завантажує картку, аналізує, зберігає та оновлює БД.
    """
    if not message.from_user or not message.photo:
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    data = await state.get_data()
    last_id = data.get("last_bot_message_id")

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    current = await state.get_state()
    mode_map = {
        RegistrationFSM.waiting_for_basic_photo.state: "basic",
        RegistrationFSM.waiting_for_stats_photo.state: "stats",
        RegistrationFSM.waiting_for_heroes_photo.state: "heroes",
    }
    mode = mode_map.get(current)
    if not mode or not last_id:
        await bot.send_message(chat_id, "Сталася помилка. Спробуйте /profile заново.")
        await state.clear()
        return

    thinking = await bot.edit_message_text(
        chat_id=chat_id,
        message_id=last_id,
        text=f"Аналізую скріншот ({mode})... 🤖",
    )

    try:
        # Отримуємо найбільший варіант фото
        largest: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
        file_info = await bot.get_file(largest.file_id)
        image_bytes = (await bot.download_file(file_info.file_path)).read()

        permanent_url = await file_resilience_manager.optimize_and_store_image(
            image_bytes, user_id, mode
        )

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            result = await gpt.analyze_user_profile(image_b64, mode=mode)

        if not result or "error" in result:
            err = result.get("error", "Не вдалося розпізнати дані.")
            await thinking.edit_text(f"❌ Помилка аналізу: {err}")
            await state.clear()
            return

        update_payload: Dict[str, Any] = {"telegram_id": user_id}
        if mode == "basic":
            ml = result.get("mlbb_id_server", "0 (0)").split()
            update_payload.update({
                "nickname": result.get("game_nickname"),
                "player_id": int(ml[0]),
                "server_id": int(ml[1].strip("()")),
                "current_rank": result.get("highest_rank_season"),
                "total_matches": result.get("matches_played"),
                "basic_profile_file_id": largest.file_id,
                "basic_profile_permanent_url": permanent_url,
            })
        elif mode == "stats":
            main = result.get("main_indicators", {})
            update_payload.update({
                "total_matches": main.get("matches_played"),
                "win_rate": main.get("win_rate"),
                "stats_photo_file_id": largest.file_id,
                "stats_photo_permanent_url": permanent_url,
            })
        else:  # heroes
            fav = result.get("favorite_heroes", [])
            heroes_str = ", ".join(h.get("hero_name", "") for h in fav if h.get("hero_name"))
            update_payload.update({
                "favorite_heroes": heroes_str,
                "heroes_photo_file_id": largest.file_id,
                "heroes_photo_permanent_url": permanent_url,
            })

        status = await add_or_update_user(update_payload)
        if status == "success":
            await show_profile_menu(
                bot, chat_id, user_id, message_to_delete_id=thinking.message_id
            )
        elif status == "conflict":
            await thinking.edit_text(
                "🛡️ Конфлікт: цей профіль вже зареєстровано іншим Telegram."
            )
        else:
            await thinking.edit_text("❌ Помилка збереження. Спробуйте пізніше.")

    except Exception as e:
        logger.exception(f"Помилка обробки фото ({mode}): {e}")
        await thinking.edit_text("Критична помилка. Спробуйте ще раз.")
    finally:
        await state.clear()


# === Обробники меню та каруселі ===

@registration_router.callback_query(F.data == "profile_show_menu")
async def profile_show_menu_handler(callback: CallbackQuery):
    """Відкриває карусель з першої сторінки профілю."""
    await show_profile_carousel(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        user_id=callback.from_user.id,
        page_index=0,
    )
    await callback.answer()


@registration_router.callback_query(F.data.startswith("profile_prev_page"))
async def profile_prev_page_handler(callback: CallbackQuery):
    """Перша кнопка пагінації: попередня сторінка."""
    new_idx = int(callback.data.split(":")[-1])
    await show_profile_carousel(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        user_id=callback.from_user.id,
        page_index=new_idx,
    )
    await callback.answer()


@registration_router.callback_query(F.data.startswith("profile_next_page"))
async def profile_next_page_handler(callback: CallbackQuery):
    """Друга кнопка пагінації: наступна сторінка."""
    new_idx = int(callback.data.split(":")[-1])
    await show_profile_carousel(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        user_id=callback.from_user.id,
        page_index=new_idx,
    )
    await callback.answer()


@registration_router.callback_query(F.data == "profile_hide_menu")
async def profile_hide_menu_handler(callback: CallbackQuery):
    """Приховує меню та повертає однокнопковий режим."""
    await callback.message.edit_reply_markup(
        reply_markup=create_profile_menu_keyboard()
    )
    await callback.answer()


@registration_router.callback_query(F.data == "profile_delete")
async def profile_delete_handler(callback: CallbackQuery, state: FSMContext):
    """Обробник видалення профілю: запит підтвердження."""
    await state.set_state(RegistrationFSM.confirming_deletion)
    await callback.message.edit_text(
        "Ви впевнені, що хочете видалити профіль? Це назавжди.",
        reply_markup=create_delete_confirm_keyboard(),
    )
    await callback.answer()


@registration_router.callback_query(
    RegistrationFSM.confirming_deletion, F.data == "delete_confirm_yes"
)
async def confirm_delete_profile(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Підтвердження видалення профілю."""
    user_id = callback.from_user.id
    deleted = await delete_user_by_telegram_id(user_id)
    text = "Профіль успішно видалено." if deleted else "Не вдалося видалити профіль."
    await callback.message.edit_text(text)
    await callback.answer()
    await state.clear()


@registration_router.callback_query(
    RegistrationFSM.confirming_deletion, F.data == "delete_confirm_no"
)
async def cancel_delete_profile(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Скасування видалення профілю."""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    await state.clear()
    await show_profile_menu(
        bot, chat_id, user_id, message_to_delete_id=callback.message.message_id
    )
    await callback.answer("Видалення скасовано.")


def register_registration_handlers(dp: Router) -> None:
    """Реєструє обробники для реєстрації та профілю."""
    dp.include_router(registration_router)
    logger.info("✅ Обробники реєстрації профілю зареєстровано.")