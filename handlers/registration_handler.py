"""
Обробники для процесу реєстрації та оновлення профілю користувача
з реалізацією каруселі слайдів з покращеним візуальним оформленням.
"""
import html
import base64
from typing import Any, Dict, List, Optional

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, PhotoSize, InputMediaPhoto
from aiogram.exceptions import TelegramAPIError

from states.user_states import RegistrationFSM
from keyboards.inline_keyboards import (
    create_profile_menu_keyboard,
    create_profile_menu_overview_keyboard,
    create_delete_confirm_keyboard,
)
from services.openai_service import MLBBChatGPT
from database.crud import add_or_update_user, get_user_by_telegram_id, delete_user_by_telegram_id
from utils.file_manager import file_resilience_manager
from config import OPENAI_API_KEY, logger

registration_router = Router()


def format_profile_display(user_data: Dict[str, Any]) -> str:
    """
    Форматує базову сторінку профілю з блоками та емодзі для кращого сприйняття.
    """
    nickname = html.escape(user_data.get("nickname", "Не вказано"))
    pid = user_data.get("player_id", "N/A")
    sid = user_data.get("server_id", "N/A")
    rank = html.escape(user_data.get("current_rank", "Не вказано") or "Не вказано")
    matches = user_data.get("total_matches", "Н/Д")
    win = user_data.get("win_rate")
    wr = f"{win}%" if win is not None else "Н/Д"
    likes = user_data.get("likes_received", "Н/Д")
    loc = html.escape(user_data.get("location", "Не вказано") or "Не вказано")
    squad = html.escape(user_data.get("squad_name", "Не вказано") or "Не вказано")

    # Емодзі-акценти
    rank_emoji = "🏆" if "Міфічна" in rank else "🎖️"
    wr_emoji = "🔥" if win and win >= 60 else "📊"

    lines = [
        "🎮 <b>ПРОФІЛЬ ГРАВЦЯ</b>",
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
        f"┃ 👤 <b>Нікнейм:</b> {nickname}",
        f"┃ 🆔 <b>ID:</b> {pid} ({sid})",
        f"┃ {rank_emoji} <b>Ранг:</b> {rank}",
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        "",
        "⚔️ <b>ІГРОВА СТАТИСТИКА</b>",
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
        f"┃ 🎯 <b>Матчів:</b> {matches}",
        f"┃ {wr_emoji} <b>Win Rate:</b> {wr}",
        f"┃ 👍 <b>Лайків:</b> {likes}",
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        "",
        "🌍 <b>ЛОКАЦІЯ / СКВАД</b>",
        "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
        f"┃ 📍 <b>Локація:</b> {loc}",
        f"┃ 🛡️ <b>Сквад:</b> {squad}",
        "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
    ]
    return "\n".join(lines)


async def build_profile_pages(user_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Формує карусель профілю: basic → stats → heroes → avatar,
    кожна сторінка з власним заголовком та емодзі.
    """
    pages: List[Dict[str, str]] = []

    # Basic profile
    pages.append({
        "photo": user_data.get("basic_profile_permanent_url", ""),
        "caption": format_profile_display(user_data),
    })

    # Detailed stats
    stats_url = user_data.get("stats_photo_permanent_url")
    if stats_url:
        mvp = user_data.get('mvp_count', 0)
        legendary = user_data.get('legendary_count', 0)
        maniac = user_data.get('maniac_count', 0)
        kda = user_data.get('kda_ratio', 0.0)
        gold = user_data.get('avg_gold_per_min', 0)
        dmg = user_data.get('avg_hero_dmg_per_min', 0)

        stats_lines = [
            "📊 <b>ДЕТАЛЬНА СТАТИСТИКА</b>",
            "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓",
            f"┃ 🌟 MVP: <b>{mvp}</b>",
            f"┃ 🔥 Legendary: <b>{legendary}</b>",
            f"┃ 🎭 Maniac: <b>{maniac}</b>",
            "┃",
            f"┃ 📈 KDA: <b>{kda:.2f}</b>",
            f"┃ 💰 Gold/Min: <b>{gold}</b>",
            f"┃ ⚔️ Dmg/Min: <b>{dmg}</b>",
            "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛",
        ]
        pages.append({"photo": stats_url, "caption": "\n".join(stats_lines)})

    # Top-3 heroes
    heroes_url = user_data.get("heroes_photo_permanent_url")
    if heroes_url:
        hero_lines = ["🦸 <b>ТОП-3 ГЕРОЇ</b>", "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"]
        medals = ["🥇", "🥈", "🥉"]
        for i in range(1, 4):
            name = user_data.get(f"hero{i}_name")
            matches = user_data.get(f"hero{i}_matches", 0)
            win_rate = user_data.get(f"hero{i}_win_rate", 0.0)
            if name:
                hero_lines.append(f"┃ {medals[i-1]} <b>{html.escape(name)}</b>")
                hero_lines.append(f"┃    🎯 Матчів: <b>{matches}</b> | 📊 WR: <b>{win_rate:.1f}%</b>")
                if i < 3:
                    hero_lines.append("┃")
        hero_lines.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        pages.append({"photo": heroes_url, "caption": "\n".join(hero_lines)})

    # Avatar
    avatar_url = user_data.get("avatar_permanent_url")
    if avatar_url:
        pages.append({
            "photo": avatar_url,
            "caption": "🖼️ <b>ВАШ АВАТАР</b>\n\nПерсональне зображення профілю.",
        })

    return pages


async def show_profile_carousel(
    bot: Bot,
    chat_id: int,
    message_id: int,
    user_id: int,
    page_index: int,
) -> None:
    """
    Оновлює карусель: змінює фото, підпис та клавіатуру відповідно до сторінки.
    """
    user_data = await get_user_by_telegram_id(user_id) or {}
    pages = await build_profile_pages(user_data)
    total = len(pages)
    if total == 0:
        return

    idx = max(0, min(page_index, total - 1))
    page = pages[idx]

    # Замінюємо фото
    if page["photo"]:
        media = InputMediaPhoto(media=page["photo"])
        try:
            await bot.edit_message_media(chat_id=chat_id, message_id=message_id, media=media)
        except TelegramAPIError as e:
            logger.warning(f"Не вдалося оновити media: {e}")

    # Замінюємо підпис і оновлюємо меню
    await bot.edit_message_caption(
        chat_id=chat_id,
        message_id=message_id,
        caption=page["caption"],
        parse_mode="HTML",
        reply_markup=create_profile_menu_overview_keyboard(current_page=idx+1, total_pages=total),
    )


async def show_profile_menu(
    bot: Bot,
    chat_id: int,
    user_id: int,
    message_to_delete_id: Optional[int] = None,
) -> None:
    """
    Відправляє першу сторінку профілю з однією кнопкою "Меню".
    """
    if message_to_delete_id:
        try:
            await bot.delete_message(chat_id, message_to_delete_id)
        except TelegramAPIError:
            pass

    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        await bot.send_message(chat_id, "Не знайдено профіль. Використайте /profile.")
        return

    url = user_data.get("basic_profile_permanent_url")
    caption = format_profile_display(user_data)
    if url:
        await bot.send_photo(chat_id, url, caption=caption, parse_mode="HTML",
                             reply_markup=create_profile_menu_keyboard())
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML",
                               reply_markup=create_profile_menu_keyboard())


@registration_router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обробник команди /profile."""
    if not message.from_user:
        return
    uid = message.from_user.id
    cid = message.chat.id
    try:
        await message.delete()
    except TelegramAPIError:
        pass
    await state.clear()
    if await get_user_by_telegram_id(uid):
        await show_profile_menu(bot, cid, uid)
    else:
        await state.set_state(RegistrationFSM.waiting_for_basic_photo)
        sent = await bot.send_message(
            cid,
            "👋 Вітаю! Надішліть, будь ласка, скріншот вашого профілю для реєстрації. 📸"
        )
        await state.update_data(last_bot_message_id=sent.message_id)


@registration_router.callback_query(F.data == "profile_update_basic")
async def profile_update_basic_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Перезапит базового скріншота."""
    await state.set_state(RegistrationFSM.waiting_for_basic_photo)
    try:
        await callback.message.delete()
    except TelegramAPIError:
        pass
    sent = await callback.bot.send_message(
        callback.message.chat.id,
        "Будь ласка, надішліть новий скріншот основної сторінки профілю."
    )
    await state.update_data(last_bot_message_id=sent.message_id)
    await callback.answer()


@registration_router.callback_query(F.data == "profile_update_stats")
async def profile_update_stats_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Запит скріншота статистики."""
    await state.set_state(RegistrationFSM.waiting_for_stats_photo)
    try:
        await callback.message.delete()
    except TelegramAPIError:
        pass
    sent = await callback.bot.send_message(
        callback.message.chat.id,
        "Надішліть, будь ласка, скріншот розділу 'Statistics' → 'All Seasons'."
    )
    await state.update_data(last_bot_message_id=sent.message_id)
    await callback.answer()


@registration_router.callback_query(F.data == "profile_update_heroes")
async def profile_update_heroes_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Запит скріншота улюблених героїв."""
    await state.set_state(RegistrationFSM.waiting_for_heroes_photo)
    try:
        await callback.message.delete()
    except TelegramAPIError:
        pass
    sent = await callback.bot.send_message(
        callback.message.chat.id,
        "Надішліть, будь ласка, скріншот розділу 'Favorite' → 'All Seasons' (топ-3)."
    )
    await state.update_data(last_bot_message_id=sent.message_id)
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
) -> None:
    """Універсальний обробник отримання фото в станах реєстрації."""
    if not message.from_user or not message.photo:
        return
    uid = message.from_user.id
    cid = message.chat.id
    data = await state.get_data()
    last_id = data.get("last_bot_message_id")
    try:
        await message.delete()
    except TelegramAPIError:
        pass

    mode = {
        RegistrationFSM.waiting_for_basic_photo.state: "basic",
        RegistrationFSM.waiting_for_stats_photo.state: "stats",
        RegistrationFSM.waiting_for_heroes_photo.state: "heroes",
    }.get(await state.get_state())
    if not mode or not last_id:
        await bot.send_message(cid, "Сталася помилка. Спробуйте /profile ще раз.")
        await state.clear()
        return

    thinking = await bot.edit_message_text(
        chat_id=cid, message_id=last_id, text=f"Аналізую ваш скріншот ({mode})... 🤖"
    )
    try:
        largest: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
        file_info = await bot.get_file(largest.file_id)
        img_bytes = (await bot.download_file(file_info.file_path)).read()
        url = await file_resilience_manager.optimize_and_store_image(img_bytes, uid, mode)
        b64 = base64.b64encode(img_bytes).decode("utf-8")

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            result = await gpt.analyze_user_profile(b64, mode=mode)

        if not result or "error" in result:
            err = result.get("error", "Не вдалося розпізнати дані.")
            await thinking.edit_text(f"❌ Помилка аналізу: {err}")
            await state.clear()
            return

        payload: Dict[str, Any] = {"telegram_id": uid}
        if mode == "basic":
            ml = result.get("mlbb_id_server", "0 (0)").split()
            payload.update({
                "nickname": result.get("game_nickname"),
                "player_id": int(ml[0]),
                "server_id": int(ml[1].strip("()")),
                "current_rank": result.get("highest_rank_season"),
                "total_matches": result.get("matches_played"),
                "likes_received": result.get("likes_received"),
                "location": result.get("location"),
                "squad_name": result.get("squad_name"),
                "basic_profile_file_id": largest.file_id,
                "basic_profile_permanent_url": url,
            })
        elif mode == "stats":
            mi = result.get("main_indicators", {})
            achL = result.get("achievements_left_column", {})
            achR = result.get("achievements_right_column", {})
            det = result.get("details_panel", {})
            payload.update({
                "total_matches": mi.get("matches_played"),
                "win_rate": mi.get("win_rate"),
                "stats_filter_type": result.get("stats_filter_type"),
                "mvp_count": mi.get("mvp_count"),
                "legendary_count": achL.get("legendary_count"),
                "maniac_count": achL.get("maniac_count"),
                "double_kill_count": achL.get("double_kill_count"),
                "most_kills_in_one_game": achL.get("most_kills_in_one_game"),
                "longest_win_streak": achL.get("longest_win_streak"),
                "highest_dmg_per_min": achL.get("highest_dmg_per_min"),
                "highest_gold_per_min": achL.get("highest_gold_per_min"),
                "savage_count": achR.get("savage_count"),
                "triple_kill_count": achR.get("triple_kill_count"),
                "mvp_loss_count": achR.get("mvp_loss_count"),
                "most_assists_in_one_game": achR.get("most_assists_in_one_game"),
                "first_blood_count": achR.get("first_blood_count"),
                "highest_dmg_taken_per_min": achR.get("highest_dmg_taken_per_min"),
                "kda_ratio": det.get("kda_ratio"),
                "teamfight_participation_rate": det.get("teamfight_participation_rate"),
                "avg_gold_per_min": det.get("avg_gold_per_min"),
                "avg_hero_dmg_per_min": det.get("avg_hero_dmg_per_min"),
                "avg_deaths_per_match": det.get("avg_deaths_per_match"),
                "avg_turret_dmg_per_match": det.get("avg_turret_dmg_per_match"),
                "stats_photo_file_id": largest.file_id,
                "stats_photo_permanent_url": url,
            })
        else:
            fav = result.get("favorite_heroes", [])
            for idx, hero in enumerate(fav[:3], start=1):
                payload.update({
                    f"hero{idx}_name": hero.get("hero_name"),
                    f"hero{idx}_matches": hero.get("matches"),
                    f"hero{idx}_win_rate": hero.get("win_rate"),
                })
            payload.update({
                "heroes_photo_file_id": largest.file_id,
                "heroes_photo_permanent_url": url,
            })

        status = await add_or_update_user(payload)
        if status == "success":
            await show_profile_menu(bot, cid, uid, message_to_delete_id=thinking.message_id)
        elif status == "conflict":
            await thinking.edit_text("🛡️ Конфлікт: цей профіль вже зареєстровано іншим акаунтом.")
        else:
            await thinking.edit_text("❌ Помилка збереження. Спробуйте пізніше.")
    except Exception as e:
        logger.exception(f"Критична помилка обробки фото ({mode}): {e}")
        await thinking.edit_text("Сталася неочікувана помилка. Спробуйте ще раз.")
    finally:
        await state.clear()


@registration_router.callback_query(F.data == "profile_show_menu")
async def profile_show_menu_handler(callback: CallbackQuery) -> None:
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
async def profile_prev_page_handler(callback: CallbackQuery) -> None:
    """Перемикає на попередню сторінку каруселі."""
    idx = int(callback.data.split(":", 1)[1]) - 1
    await show_profile_carousel(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        user_id=callback.from_user.id,
        page_index=idx,
    )
    await callback.answer()


@registration_router.callback_query(F.data.startswith("profile_next_page"))
async def profile_next_page_handler(callback: CallbackQuery) -> None:
    """Перемикає на наступну сторінку каруселі."""
    idx = int(callback.data.split(":", 1)[1]) - 1
    await show_profile_carousel(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        user_id=callback.from_user.id,
        page_index=idx,
    )
    await callback.answer()


@registration_router.callback_query(F.data == "profile_hide_menu")
async def profile_hide_menu_handler(callback: CallbackQuery) -> None:
    """Приховує меню та повертає однокнопковий режим."""
    await callback.message.edit_reply_markup(reply_markup=create_profile_menu_keyboard())
    await callback.answer()


@registration_router.callback_query(F.data == "profile_delete")
async def profile_delete_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Запит на підтвердження видалення профілю."""
    await state.set_state(RegistrationFSM.confirming_deletion)
    text = "Ви впевнені, що хочете видалити профіль? Це назавжди."
    if callback.message.photo:
        await callback.message.edit_caption(text, reply_markup=create_delete_confirm_keyboard())
    else:
        await callback.message.edit_text(text, reply_markup=create_delete_confirm_keyboard())
    await callback.answer()


@registration_router.callback_query(
    RegistrationFSM.confirming_deletion, F.data == "delete_confirm_yes"
)
async def confirm_delete_profile(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Підтвердження видалення профілю."""
    uid = callback.from_user.id
    deleted = await delete_user_by_telegram_id(uid)
    text = "Профіль успішно видалено." if deleted else "Не вдалося видалити профіль."
    await callback.message.edit_text(text)
    await callback.answer()
    await state.clear()


@registration_router.callback_query(
    RegistrationFSM.confirming_deletion, F.data == "delete_confirm_no"
)
async def cancel_delete_profile(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Скасування видалення профілю."""
    uid = callback.from_user.id
    chat = callback.message.chat.id
    await state.clear()
    await show_profile_menu(bot, chat, uid, message_to_delete_id=callback.message.message_id)
    await callback.answer("Видалення скасовано.")


def register_registration_handlers(dp: Router) -> None:
    """Реєструє обробники реєстрації профілю."""
    dp.include_router(registration_router)
    logger.info("✅ Обробники реєстрації профілю зареєстровано.")