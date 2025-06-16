import base64
import html
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

# Імпорти з проєкту
from config import OPENAI_API_KEY, logger # Використовуємо logger з config
from services.openai_service import MLBBChatGPT, PROFILE_SCREENSHOT_PROMPT
from states.vision_states import VisionAnalysisStates
from utils.message_utils import send_message_in_chunks
# from ..config import OPENAI_API_KEY, logger
# from ..services.openai_service import MLBBChatGPT, PROFILE_SCREENSHOT_PROMPT
# from ..states.vision_states import VisionAnalysisStates
# from ..utils.message_utils import send_message_in_chunks
# Потрібно буде також імпортувати cmd_go, якщо він використовується для переходу
# from .general_handlers import cmd_go # Або передавати функцію


# Ініціалізація логера для цього файлу, якщо не використовується глобальний
# logger = logging.getLogger(__name__)

async def cmd_analyze_profile(message: Message, state: FSMContext):
    """Обробник команди /analyzeprofile. Запитує скріншот профілю."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) активував /analyzeprofile.")
    
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
        "Будь ласка, надішли мені скріншот свого профілю з Mobile Legends.\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

async def handle_profile_screenshot(message: Message, state: FSMContext, bot: Bot): # Додано bot
    """Обробляє надісланий скріншот профілю."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    chat_id = message.chat.id
    logger.info(f"Отримано скріншот профілю від {user_name_escaped} (ID: {user_id}).")

    if not message.photo: # Перевірка, чи це дійсно фото
        await message.answer("Щось пішло не так. Будь ласка, надішли саме фото (скріншот).")
        return

    photo_file_id = message.photo[-1].file_id # Беремо найбільше фото

    try:
        # Видаляємо оригінальне повідомлення користувача зі скріншотом, якщо бот має права
        await message.delete()
        logger.info(f"Повідомлення користувача {user_name_escaped} зі скріншотом видалено.")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped} зі скріншотом: {e}")

    # Зберігаємо дані для наступного кроку
    await state.update_data(vision_photo_file_id=photo_file_id, original_user_name=user_name_escaped)

    caption_text = "Скріншот профілю отримано.\nНатисніть «🔍 Аналіз», щоб дізнатися більше."

    analyze_button = InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")
    delete_preview_button = InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[analyze_button, delete_preview_button]])

    try:
        # Надсилаємо фото назад користувачу, але вже від імені бота, з кнопками
        sent_message = await bot.send_photo( # Використовуємо переданий bot
            chat_id=chat_id,
            photo=photo_file_id,
            caption=caption_text,
            reply_markup=keyboard
        )
        await state.update_data(bot_message_id_for_analysis=sent_message.message_id)
        await state.set_state(VisionAnalysisStates.awaiting_analysis_trigger)
        logger.info(f"Скріншот від {user_name_escaped} повторно надіслано ботом з кнопками. Новий state: awaiting_analysis_trigger")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для аналізу для {user_name_escaped}: {e}")
        try:
            await bot.send_message(chat_id, "Не вдалося обробити ваш запит на аналіз. Спробуйте ще раз.")
        except TelegramAPIError as send_err:
            logger.error(f"Не вдалося надіслати повідомлення про помилку обробки аналізу для {user_name_escaped}: {send_err}")
        await state.clear()


async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext, bot: Bot): # Додано bot
    """Обробляє натискання кнопки "Аналіз", викликає Vision API та надсилає результат."""
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear()
        return

    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id # ID повідомлення бота з фото та кнопкою

    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець") # Отримуємо ім'я користувача зі стану

    try:
        # Редагуємо повідомлення, показуючи, що обробка почалася, і видаляємо кнопки
        if callback_query.message.caption: # Якщо є підпис (має бути)
            await callback_query.message.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {user_name}...",
                reply_markup=None # Видаляємо клавіатуру
            )
        else: # На випадок, якщо підпису не було (не повинно трапитися)
             await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...") # Підтверджуємо натискання кнопки
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name}: {e}")

    photo_file_id = user_data.get("vision_photo_file_id")

    if not photo_file_id:
        logger.error(f"File_id не знайдено в стані для аналізу для {user_name}.")
        try:
            if callback_query.message.caption: 
                await callback_query.message.edit_caption(caption=f"Помилка, {user_name}: дані для аналізу втрачено. Спробуйте надіслати скріншот знову.")
        except TelegramAPIError: pass 
        await state.clear()
        return

    final_caption_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"

    try:
        file_info = await bot.get_file(photo_file_id) # Використовуємо переданий bot
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")

        downloaded_file_io = await bot.download_file(file_info.file_path) # Використовуємо переданий bot
        if downloaded_file_io is None: 
            raise ValueError("Не вдалося завантажити файл з Telegram для аналізу (download_file повернув None).")
        
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer: # Використовуємо OPENAI_API_KEY з config
            # Використовуємо PROFILE_SCREENSHOT_PROMPT з openai_service
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, PROFILE_SCREENSHOT_PROMPT)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз профілю (JSON) для {user_name}: {analysis_result_json}")
                response_parts = [f"<b>Детальний аналіз твого профілю, {user_name}:</b>"]
                fields_translation = {
                    "game_nickname": "🎮 Нікнейм", "mlbb_id_server": "🆔 ID (Сервер)",
                    "highest_rank_season": "🌟 Найвищий ранг (сезон)",
                    "matches_played": "⚔️ Матчів зіграно", "likes_received": "👍 Лайків отримано",
                    "location": "🌍 Локація", "squad_name": "🛡️ Сквад"
                }
                has_data = False
                for key, readable_name in fields_translation.items():
                    value = analysis_result_json.get(key)
                    if value is not None: 
                        display_value = str(value)
                        if key == "highest_rank_season" and ("★" in display_value or "зірок" in display_value.lower() or "слава" in display_value.lower()):
                            if "★" not in display_value: 
                                 display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                            display_value = re.sub(r'\s+★', '★', display_value) 
                        response_parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
                        has_data = True
                    else:
                         response_parts.append(f"<b>{readable_name}:</b> <i>не розпізнано</i>")
                
                if not has_data and analysis_result_json.get("raw_response"): 
                     response_parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>\nДеталі від ШІ: ...{html.escape(analysis_result_json['raw_response'][-100:])}")
                elif not has_data:
                     response_parts.append(f"\n<i>Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")

                structured_data_text = "\n".join(response_parts)
                
                profile_description_plain = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                # Оскільки PROFILE_DESCRIPTION_PROMPT_TEMPLATE вимагає чистого тексту, екрануємо його для HTML
                final_caption_text = f"{structured_data_text}\n\n{html.escape(profile_description_plain)}"

            else:
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу профілю (JSON) для {user_name}: {error_msg}")
                final_caption_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
                if analysis_result_json and analysis_result_json.get("raw_response"):
                    final_caption_text += f"\nДеталі: {html.escape(str(analysis_result_json.get('raw_response'))[:100])}..."
                elif analysis_result_json and analysis_result_json.get("details"):
                     final_caption_text += f"\nДеталі: {html.escape(str(analysis_result_json.get('details'))[:100])}..."

    except TelegramAPIError as e:
        logger.exception(f"Telegram API помилка під час обробки файлу для {user_name}: {e}")
        final_caption_text = f"Пробач, {user_name}, виникла проблема з доступом до файлу скріншота в Telegram."
    except ValueError as e: 
        logger.exception(f"Помилка значення під час обробки файлу для {user_name}: {e}")
        final_caption_text = f"На жаль, {user_name}, не вдалося коректно обробити файл скріншота."
    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота профілю для {user_name}: {e}")
        final_caption_text = f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."


    try:
        if callback_query.message: 
            if len(final_caption_text) > 1024: # Ліміт довжини підпису до медіа
                logger.warning(f"Підпис до фото для {user_name} задовгий ({len(final_caption_text)} символів). Редагую фото без підпису і надсилаю текст окремо.")
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None) # Видаляємо кнопки з фото
                await send_message_in_chunks(bot, chat_id, final_caption_text, ParseMode.HTML) # Використовуємо переданий bot
            else:
                await bot.edit_message_caption( # Використовуємо переданий bot
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=final_caption_text,
                    reply_markup=None, # Кнопки вже видалені або видаляються тут
                    parse_mode=ParseMode.HTML
                )
            logger.info(f"Результати аналізу для {user_name} відредаговано/надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати/надіслати повідомлення з результатами аналізу для {user_name}: {e}. Спроба надіслати як нове.")
        try:
            await send_message_in_chunks(bot, chat_id, final_caption_text, ParseMode.HTML) # Використовуємо переданий bot
        except Exception as send_err:
            logger.error(f"Не вдалося надіслати нове повідомлення з аналізом для {user_name}: {send_err}")
            # Остання спроба повідомити користувача про помилку
            if callback_query.message: 
                try:
                    await bot.send_message(chat_id, f"Вибачте, {user_name}, сталася помилка при відображенні результатів аналізу. Спробуйте пізніше.")
                except Exception as final_fallback_err:
                     logger.error(f"Не вдалося надіслати навіть текстове повідомлення про помилку аналізу для {user_name}: {final_fallback_err}")

    await state.clear()


async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext):
    """ Обробляє натискання кнопки "Видалити" на повідомленні-прев'ю скріншота. """
    if not callback_query.message:
        logger.error("delete_bot_message_callback: callback_query.message is None.")
        await callback_query.answer("Помилка видалення.", show_alert=True)
        return
    try:
        await callback_query.message.delete()
        await callback_query.answer("Повідомлення видалено.")
        current_state_str = await state.get_state()
        # Очищаємо стан тільки якщо він був пов'язаний з цим потоком аналізу
        if current_state_str == VisionAnalysisStates.awaiting_analysis_trigger.state:
            user_name = (await state.get_data()).get("original_user_name", "Користувач")
            logger.info(f"Прев'ю аналізу видалено користувачем {user_name}, стан очищено.")
            await state.clear()
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота (ймовірно, прев'ю): {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)


async def cancel_profile_analysis(message: Message, state: FSMContext, bot: Bot): # Додано bot
    """Обробник команди /cancel під час аналізу профілю."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    logger.info(f"Користувач {user_name_escaped} скасував аналіз профілю командою /cancel.")

    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id and message.chat: 
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id) # Використовуємо переданий bot
            logger.info(f"Видалено повідомлення-прев'ю бота (ID: {bot_message_id}) після скасування аналізу {user_name_escaped}.")
        except TelegramAPIError: 
            logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота (ID: {bot_message_id}) при скасуванні для {user_name_escaped}.")

    await state.clear()
    await message.reply(f"Аналіз скріншота скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go.")


async def handle_wrong_input_for_profile_screenshot(message: Message, state: FSMContext, bot: Bot, cmd_go_handler): # Додано bot та cmd_go_handler
    """Обробляє некоректне введення під час очікування скріншота або тригера аналізу."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")

    # Явна перевірка на команду /cancel
    if message.text and message.text.lower() == "/cancel":
        await cancel_profile_analysis(message, state, bot) # Передаємо bot
        return

    # Якщо користувач ввів /go, перенаправляємо на обробник /go
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data()
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try: await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id) # Використовуємо переданий bot
            except TelegramAPIError: pass
        await state.clear()
        await cmd_go_handler(message, state, bot) # Викликаємо переданий обробник cmd_go
        return 

    current_state_name = await state.get_state()
    if current_state_name == VisionAnalysisStates.awaiting_profile_screenshot.state:
        logger.info(f"Користувач {user_name_escaped} надіслав не фото у стані awaiting_profile_screenshot. Пропоную скасувати або надіслати фото.")
        await message.reply(f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) свого профілю або команду /cancel для скасування.")
    elif current_state_name == VisionAnalysisStates.awaiting_analysis_trigger.state:
        logger.info(f"Користувач {user_name_escaped} надіслав '{html.escape(message.text or 'не текстове повідомлення')}' у стані awaiting_analysis_trigger. Пропоную скасувати.")
        await message.reply(f"Очікувалася дія з аналізом (кнопка під фото) або команда /cancel, {user_name_escaped}.")
    else: 
        logger.info(f"Користувач {user_name_escaped} надіслав некоректне введення у стані аналізу. Пропоную скасувати.")
        await message.reply(f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.")

# Функція для реєстрації обробників цього файлу
def register_vision_handlers(dp: Dispatcher, cmd_go_handler_func): # Додано cmd_go_handler_func
    dp.message.register(cmd_analyze_profile, Command("analyzeprofile"))
    
    # Обробник для фотографій у стані awaiting_profile_screenshot
    dp.message.register(handle_profile_screenshot, VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
    
    # Обробник для колбеку кнопки "Аналіз"
    dp.callback_query.register(trigger_vision_analysis_callback, F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
    
    # Обробник для колбеку кнопки "Видалити"
    dp.callback_query.register(delete_bot_message_callback, F.data == "delete_bot_message")
    
    # Обробники для команди /cancel у відповідних станах
    dp.message.register(cancel_profile_analysis, VisionAnalysisStates.awaiting_profile_screenshot, Command("cancel"))
    dp.message.register(cancel_profile_analysis, VisionAnalysisStates.awaiting_analysis_trigger, Command("cancel"))

    # Обробники для некоректного вводу у станах (мають бути останніми для цих станів)
    # Передаємо cmd_go_handler_func в lambda, щоб зафіксувати його для виклику
    dp.message.register(
        lambda message, state, bot: handle_wrong_input_for_profile_screenshot(message, state, bot, cmd_go_handler_func),
        VisionAnalysisStates.awaiting_profile_screenshot
    )
    dp.message.register(
        lambda message, state, bot: handle_wrong_input_for_profile_screenshot(message, state, bot, cmd_go_handler_func),
        VisionAnalysisStates.awaiting_analysis_trigger
    )
    logger.info("Обробники аналізу зображень зареєстровано.")
