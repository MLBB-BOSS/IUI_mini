"""
Головний модуль обробників загального призначення.
Цей файл містить всю логіку для:
- Обробки стартових команд (/start, /go).
- Адаптивної відповіді на тригерні фрази в чаті.
- Покрокового створення ігрового лобі (паті) з використанням FSM.
- 🆕 Універсального розпізнавання та обробки зображень.
- Глобальної обробки помилок.

Архітектура побудована на двох роутерах для керування пріоритетами:
1. `party_router`: Перехоплює специфічні запити на створення паті.
2. `general_router`: Обробляє всі інші загальні команди, повідомлення та зображення.
"""
import html
import logging
import re
import time
import base64
import io
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Deque, List
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, Update, CallbackQuery, PhotoSize
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
# Імпорт для визначення станів (FSM)
from aiogram.fsm.state import StatesGroup, State

# Імпорти з нашого проєкту
from config import (
    ADMIN_USER_ID, WELCOME_IMAGE_URL, OPENAI_API_KEY, logger,
    CONVERSATIONAL_TRIGGERS, MAX_CHAT_HISTORY_LENGTH,
    BOT_NAMES, CONVERSATIONAL_COOLDOWN_SECONDS,
    # 🆕 Нові імпорти для Vision
    VISION_AUTO_RESPONSE_ENABLED, VISION_RESPONSE_COOLDOWN_SECONDS, 
    VISION_MAX_IMAGE_SIZE_MB, VISION_CONTENT_EMOJIS
)
from services.openai_service import MLBBChatGPT
from utils.message_utils import send_message_in_chunks
# Імпортуємо всі необхідні клавіатури
from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard,
    create_role_selection_keyboard,
    create_dynamic_lobby_keyboard
)

# === ВИЗНАЧЕННЯ СТАНІВ FSM ===
# Дотримуючись твого правила "не створювати зайвих файлів",
# ми визначаємо стани тут для повної інкапсуляції логіки.
class PartyCreationFSM(StatesGroup):
    """
    Стани для покрокового процесу створення паті.
    Використовується для ведення діалогу з користувачем.
    """
    waiting_for_confirmation = State()
    waiting_for_role_selection = State()


# === СХОВИЩА ДАНИХ У ПАМ'ЯТІ ===
# Історія повідомлень для кожного чату
chat_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(lambda: deque(maxlen=MAX_CHAT_HISTORY_LENGTH))
# Кулдауни для пасивних відповідей у кожному чаті
chat_cooldowns: Dict[int, float] = {}
# 🆕 Кулдауни для Vision відповідей у кожному чаті
vision_cooldowns: Dict[int, float] = {}
# Сховище для активних лобі. УВАГА: для production варто використовувати Redis або БД.
active_lobbies: Dict[str, Dict] = {}
# Глобальний список ролей для гри
ALL_ROLES: List[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]


# === ІНІЦІАЛІЗАЦІЯ РОУТЕРІВ ===
# Використовуємо два роутери для контролю пріоритету обробки.
# `party_router` буде перевірятись першим.
party_router = Router()
general_router = Router()


# === ДОПОМІЖНІ ФУНКЦІЇ ===

def get_user_display_name(user: Optional[types.User]) -> str:
    """
    Витягує найкраще доступне ім'я користувача для звернення.
    
    Args:
        user: Об'єкт користувача Telegram або None.
        
    Returns:
        Відформатоване ім'я для звернення (завжди повертає валідний рядок).
    """
    if not user:
        return "друже"
    
    # Пріоритет: first_name -> username -> "друже"
    if user.first_name and user.first_name.strip():
        return html.escape(user.first_name.strip())
    elif user.username and user.username.strip():
        return html.escape(user.username.strip())
    else:
        return "друже"


def is_party_request_message(message: Message) -> bool:
    """
    🔧 БЕЗПЕЧНА ФУНКЦІЯ для визначення чи є повідомлення запитом на створення паті.
    
    Args:
        message: Повідомлення від користувача.
        
    Returns:
        True якщо це запит на паті, False інакше.
    """
    # Перевіряємо наявність тексту
    if not message.text:
        return False
        
    try:
        text_lower = message.text.lower()
        
        # Перевіряємо основні ключові слова паті
        has_party_keywords = re.search(r'\b(паті|пати|команду)\b', text_lower) is not None
        
        # Перевіряємо дієслова/індикатори збору
        has_action_keywords = re.search(r'\b(збир|го|шука|грат|зібра)\w*\b|\+', text_lower) is not None
        
        return has_party_keywords and has_action_keywords
        
    except (AttributeError, TypeError) as e:
        logger.warning(f"Помилка при перевірці party request: {e}")
        return False


def get_lobby_message_text(lobby_data: dict) -> str:
    """
    Форматує текст повідомлення для лобі на основі поточних даних.

    Args:
        lobby_data: Словник з даними активного лобі.

    Returns:
        Відформатований текст для повідомлення в чаті.
    """
    leader_name = html.escape(lobby_data['leader_name'])
    role_emoji_map = {"Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙", "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"}
    
    players_list = []
    taken_roles = []
    for player_id, player_info in lobby_data['players'].items():
        role = player_info['role']
        name = html.escape(player_info['name'])
        emoji = role_emoji_map.get(role, "🔹")
        players_list.append(f"• {emoji} <b>{role}:</b> {name}")
        taken_roles.append(role)

    available_roles_list = [f"• {role_emoji_map.get(r, '🔹')} {r}" for r in ALL_ROLES if r not in taken_roles]
    header = f"🔥 <b>Збираємо паті на рейтинг!</b> 🔥\n\n<b>Ініціатор:</b> {leader_name}\n"
    players_section = "<b>Учасники:</b>\n" + "\n".join(players_list)
    
    available_section = "\n\n<b>Вільні ролі:</b>\n" + "\n".join(available_roles_list) if available_roles_list else "\n\n✅ <b>Команда зібрана!</b>"
    return f"{header}\n{players_section}{available_section}"


# === ЛОГІКА СТВОРЕННЯ ПАТІ (FSM) НА `party_router` ===

# 🔧 ВИПРАВЛЕНИЙ ФІЛЬТР - використовуємо безпечну функцію
@party_router.message(F.text & F.func(is_party_request_message))
async def ask_for_party_creation(message: Message, state: FSMContext):
    """
    Крок 0: Перехоплює повідомлення про пошук паті та запускає діалог,
    переводячи користувача у стан очікування підтвердження.
    """
    user_name = get_user_display_name(message.from_user)
    logger.info(f"Виявлено запит на створення паті від {user_name}: '{message.text}'")
    
    await state.set_state(PartyCreationFSM.waiting_for_confirmation)
    await message.reply("Бачу, ти хочеш зібрати команду. Допомогти тобі?", reply_markup=create_party_confirmation_keyboard())

@party_router.callback_query(F.data == "party_cancel_creation")
async def cancel_party_creation(callback: CallbackQuery, state: FSMContext):
    """
    Обробляє відмову від допомоги на будь-якому кроці діалогу.
    Виходить зі стану FSM.
    """
    await state.clear()
    await callback.message.edit_text("Гаразд. Якщо передумаєш - звертайся! 😉")
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_confirmation, F.data == "party_start_creation")
async def prompt_for_role(callback: CallbackQuery, state: FSMContext):
    """
    Крок 1: Після підтвердження, запитує у ініціатора його роль,
    переводячи у стан очікування вибору ролі.
    """
    await state.set_state(PartyCreationFSM.waiting_for_role_selection)
    await callback.message.edit_text("Чудово! Оберіть свою роль, щоб інші знали, кого ви шукаєте:", reply_markup=create_role_selection_keyboard(ALL_ROLES))
    await callback.answer()

@party_router.callback_query(PartyCreationFSM.waiting_for_role_selection, F.data.startswith("party_role_select:"))
async def create_party_lobby(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Крок 2 (Фінал): Створює лобі, додає ініціатора як учасника,
    публікує фінальне повідомлення та виходить зі стану FSM.
    """
    user = callback.from_user
    selected_role = callback.data.split(":")[-1]
    lobby_id = str(callback.message.message_id)

    # КЛЮЧОВИЙ ФІКС: Ініціатор одразу додається до списку гравців!
    lobby_data = {
        "leader_id": user.id,
        "leader_name": get_user_display_name(user),  # Використовуємо безпечну функцію
        "players": {
            user.id: {"name": get_user_display_name(user), "role": selected_role}  # Також тут
        },
        "chat_id": callback.message.chat.id
    }
    active_lobbies[lobby_id] = lobby_data
    logger.info(f"Створено нове лобі {lobby_id} ініціатором {get_user_display_name(user)} (ID: {user.id}) з роллю {selected_role}")

    message_text = get_lobby_message_text(lobby_data)
    keyboard = create_dynamic_lobby_keyboard(lobby_id, user.id, lobby_data)
    
    await callback.message.edit_text(message_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await callback.answer(f"Ви зайняли роль: {selected_role}")
    await state.clear()


# === ІСНУЮЧІ ОБРОБНИКИ НА `general_router` ===

@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    """
    Обробник команди /start.
    Надсилає вітальне повідомлення з зображенням та описом функціоналу.
    """
    await state.clear()
    user = message.from_user
    user_name_escaped = get_user_display_name(user)  # Використовуємо безпечну функцію
    user_id = user.id if user else "невідомий"

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) запустив бота командою /start.")

    kyiv_tz = timezone(timedelta(hours=3))
    current_time_kyiv = datetime.now(kyiv_tz)
    current_hour = current_time_kyiv.hour

    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else \
                   "Доброго дня" if 12 <= current_hour < 17 else \
                   "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

    emoji = "🌅" if 5 <= current_hour < 12 else \
            "☀️" if 12 <= current_hour < 17 else \
            "🌆" if 17 <= current_hour < 22 else "🌙"

    welcome_caption = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}

Ласкаво просимо до <b>MLBB IUI mini</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.

Готовий допомогти тобі стати справжньою легендою!

<b>Що я можу для тебе зробити:</b>
🔸 Проаналізувати скріншот твого ігрового профілю.
🔸 Відповісти на запитання по грі.
🔸 🆕 Автоматично реагувати на зображення в чаті!

👇 Для початку роботи, використай одну з команд:
• <code>/analyzeprofile</code> – для аналізу скріншота.
• <code>/go &lt;твоє питання&gt;</code> – для консультації (наприклад, <code>/go найкращий танк</code>).
• Або просто надішли будь-яке зображення! 📸
"""

    try:
        await message.answer_photo(
            photo=WELCOME_IMAGE_URL,
            caption=welcome_caption,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Привітання з зображенням для {user_name_escaped} надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітальне фото для {user_name_escaped}: {e}. Спроба надіслати текст.")
        fallback_text = f"""{greeting_msg}, <b>{user_name_escaped}</b>! {emoji}
Ласкаво просимо до <b>MLBB IUI mini</b>! 🎮
Я твій AI-помічник для всього, що стосується світу Mobile Legends.
Готовий допомогти тобі стати справжньою легендою!

<b>Що я можу для тебе зробити:</b>
🔸 Проаналізувати скріншот твого ігрового профілю (команда <code>/analyzeprofile</code>).
🔸 Відповісти на запитання по грі (команда <code>/go &lt;твоє питання&gt;</code>).
🔸 🆕 Автоматично реагувати на зображення в чаті!
"""
        try:
            await message.answer(fallback_text, parse_mode=ParseMode.HTML)
            logger.info(f"Резервне текстове привітання для {user_name_escaped} надіслано.")
        except TelegramAPIError as e_text:
            logger.error(f"Не вдалося надіслати навіть резервне текстове привітання для {user_name_escaped}: {e_text}")


@general_router.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext, bot: Bot):
    """
    Обробник команди /go.
    Надсилає запит до GPT та повертає структуровану відповідь.
    """
    await state.clear()
    user = message.from_user
    user_name_escaped = get_user_display_name(user)  # Використовуємо безпечну функцію
    user_id = user.id if user else "невідомий"
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив запит з /go: '{user_query}'")

    if not user_query:
        logger.info(f"Порожній запит /go від {user_name_escaped}.")
        await message.reply(
            f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
            "Напиши своє питання після <code>/go</code>, наприклад:\n"
            "<code>/go найкращі герої для міду</code>",
            parse_mode=ParseMode.HTML
        )
        return

    thinking_messages = [
        f"🤔 {user_name_escaped}, аналізую твій запит...",
        f"🧠 Обробляю інформацію, {user_name_escaped}, щоб дати кращу пораду!",
        f"⏳ Хвилинку, {user_name_escaped}, шукаю відповідь...",
    ]
    thinking_msg_text = thinking_messages[int(time.time()) % len(thinking_messages)]
    thinking_msg: Optional[Message] = None
    try:
        thinking_msg = await message.reply(thinking_msg_text)
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати 'thinking_msg' для {user_name_escaped}: {e}")

    start_time = time.time()
    response_text = f"Вибач, {user_name_escaped}, сталася непередбачена помилка при генерації відповіді. 😔"
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}' від {user_name_escaped}: {e}")

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}' від {user_name_escaped}: {processing_time:.2f}с")

    admin_info = ""
    if user_id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.8 GPT (gpt-4.1)</i>"

    full_response_to_send = f"{response_text}{admin_info}"

    try:
        await send_message_in_chunks(
            bot_instance=bot,
            chat_id=message.chat.id,
            text=full_response_to_send,
            parse_mode=ParseMode.HTML,
            initial_message_to_edit=thinking_msg
        )
        logger.info(f"Відповідь /go для {user_name_escaped} успішно надіслано (можливо, частинами).")
    except Exception as e:
        logger.error(f"Не вдалося надіслати відповідь /go для {user_name_escaped} навіть частинами: {e}", exc_info=True)
        try:
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді. Спробуйте пізніше."
            if thinking_msg:
                 try:
                    await thinking_msg.edit_text(final_error_msg, parse_mode=None)
                 except TelegramAPIError: 
                    await message.reply(final_error_msg, parse_mode=None)
            else: 
                await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err_send:
            logger.error(f"Зовсім не вдалося надіслати фінальне повідомлення про помилку для {user_name_escaped}: {final_err_send}")


@general_router.message(F.photo)
async def handle_image_messages(message: Message, bot: Bot):
    """
    🆕 Універсальний обробник зображень.
    Автоматично розпізнає тип контенту та генерує релевантну відповідь.
    
    Працює з адаптивною логікою:
    - Пряме звернення (відповідь на зображення бота) → завжди відповідає
    - Звичайне зображення → відповідає з кулдауном та ймовірністю
    """
    if not message.photo or not message.from_user:
        return

    # Перевірка, чи увімкнений Vision модуль
    if not VISION_AUTO_RESPONSE_ENABLED:
        logger.debug("Vision модуль вимкнений у конфігурації.")
        return

    chat_id = message.chat.id
    current_time = time.time()
    current_user_name = get_user_display_name(message.from_user)
    
    try:
        bot_info = await bot.get_me()
    except Exception as e:
        logger.error(f"Не вдалося отримати інформацію про бота: {e}")
        return

    # Визначаємо пріоритет відповіді
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_caption_mention = False
    
    # Перевіряємо згадку бота в підписі до зображення
    if message.caption:
        caption_lower = message.caption.lower()
        is_caption_mention = (
            f"@{bot_info.username.lower()}" in caption_lower or
            any(re.search(r'\b' + name + r'\b', caption_lower) for name in BOT_NAMES)
        )

    # Логіка прийняття рішення про відповідь
    should_respond = False
    
    if is_reply_to_bot or is_caption_mention:
        # Пряме звернення - завжди відповідаємо
        should_respond = True
        logger.info(f"Рішення обробити зображення: пряме звернення в чаті {chat_id} від {current_user_name}.")
    else:
        # Пасивна обробка з кулдауном
        last_vision_time = vision_cooldowns.get(chat_id, 0)
        if (current_time - last_vision_time) > VISION_RESPONSE_COOLDOWN_SECONDS:
            # Додаємо елемент випадковості для більш природної поведінки
            if random.random() < 0.7:  # 70% шанс відповісти
                should_respond = True
                vision_cooldowns[chat_id] = current_time
                logger.info(f"Рішення обробити зображення: пасивний режим в чаті {chat_id} від {current_user_name}.")
            else:
                logger.info(f"Рішення проігнорувати зображення: випадковий фактор в чаті {chat_id}.")
        else:
            logger.info(f"Рішення проігнорувати зображення: активний кулдаун в чаті {chat_id}.")

    if not should_respond:
        return

    # Отримуємо найбільше зображення
    largest_photo: PhotoSize = max(message.photo, key=lambda p: p.file_size or 0)
    
    # Перевіряємо розмір файлу
    if largest_photo.file_size and largest_photo.file_size > VISION_MAX_IMAGE_SIZE_MB * 1024 * 1024:
        logger.warning(f"Зображення від {current_user_name} занадто велике: {largest_photo.file_size / (1024*1024):.1f}MB")
        await message.reply(f"Вибач, {current_user_name}, зображення занадто велике для обробки 📏")
        return

    try:
        # Завантажуємо файл
        file_info = await bot.get_file(largest_photo.file_id)
        if not file_info.file_path:
            logger.error(f"Не вдалося отримати шлях до файлу зображення від {current_user_name}")
            return

        # Отримуємо байти зображення
        image_bytes = await bot.download_file(file_info.file_path)
        if not isinstance(image_bytes, io.BytesIO):
            logger.error(f"Помилка завантаження зображення від {current_user_name}")
            return

        # Конвертуємо в base64
        image_bytes.seek(0)
        image_base64 = base64.b64encode(image_bytes.read()).decode('utf-8')
        
        logger.info(f"Зображення від {current_user_name} успішно завантажено та конвертовано. Розмір: {len(image_base64)} символів base64.")

        # Надсилаємо "thinking" індикатор тільки для прямих звернень
        thinking_msg: Optional[Message] = None
        if is_reply_to_bot or is_caption_mention:
            try:
                thinking_msg = await message.reply(f"🔍 {current_user_name}, аналізую зображення...")
            except TelegramAPIError as e:
                logger.warning(f"Не вдалося надіслати thinking_msg для {current_user_name}: {e}")

        # Викликаємо універсальний Vision аналіз
        start_time = time.time()
        try:
            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                vision_response = await gpt.analyze_image_universal(
                    image_base64=image_base64,
                    user_name=current_user_name
                )
        except Exception as e:
            logger.exception(f"Критична помилка Universal Vision для {current_user_name}: {e}")
            vision_response = None

        processing_time = time.time() - start_time
        logger.info(f"Час обробки зображення для {current_user_name}: {processing_time:.2f}с")

        # Обробляємо результат
        if vision_response and vision_response.strip():
            # Визначаємо тип контенту для емодзі
            content_type = "general"  # За замовчуванням
            response_lower = vision_response.lower()
            
            # Простий алгоритм визначення типу
            if any(word in response_lower for word in ["мем", "смішн", "жарт", "прикол", "кек", "лол"]):
                content_type = "meme"
            elif any(word in response_lower for word in ["скріншот", "гра", "матч", "катка", "профіль", "стати"]):
                content_type = "screenshot"
            elif any(word in response_lower for word in ["текст", "напис"]):
                content_type = "text"

            # Додаємо емодзі на початок (якщо його ще немає)
            emoji = VISION_CONTENT_EMOJIS.get(content_type, "🔍")
            if not any(char in vision_response[:3] for char in "🎮📸😂📝👤📊🦸⚔️📋🏆🔍"):
                final_response = f"{emoji} {vision_response}"
            else:
                final_response = vision_response

            # Надсилаємо відповідь
            try:
                if thinking_msg:
                    await thinking_msg.edit_text(final_response, parse_mode=None)
                else:
                    await message.reply(final_response, parse_mode=None)
                    
                logger.info(f"Vision відповідь для {current_user_name} успішно надіслано.")
                
                # Додаємо до історії чату
                chat_histories[chat_id].append({"role": "user", "content": f"[Надіслав зображення]"})
                chat_histories[chat_id].append({"role": "assistant", "content": final_response})
                
            except TelegramAPIError as e:
                logger.error(f"Не вдалося надіслати Vision відповідь для {current_user_name}: {e}")
                
        else:
            # Якщо Vision не зміг обробити
            logger.warning(f"Vision не зміг проаналізувати зображення від {current_user_name}")
            if thinking_msg:
                try:
                    await thinking_msg.edit_text(f"Хм, {current_user_name}, щось не можу розібрати що тут 🤔")
                except TelegramAPIError:
                    pass

    except Exception as e:
        logger.exception(f"Загальна помилка обробки зображення від {current_user_name}: {e}")
        try:
            await message.reply(f"Упс, {current_user_name}, щось пішло не так з обробкою зображення 😅")
        except TelegramAPIError:
            pass


@general_router.message(F.text)
async def handle_trigger_messages(message: Message, bot: Bot):
    """
    Обробляє текстові повідомлення за "Стратегією Адаптивної Присутності",
    щоб бот поводився як розумний учасник чату, а не спамер.
    
    🔧 КЛЮЧОВЕ ВИПРАВЛЕННЯ: Тепер завжди витягуємо актуальне ім'я з поточного повідомлення!
    """
    if not message.text or message.text.startswith('/') or not message.from_user:
        return

    # --- 1. Збір даних для аналізу ---
    text_lower = message.text.lower()
    chat_id = message.chat.id
    
    # 🎯 ГОЛОВНЕ ВИПРАВЛЕННЯ: Завжди витягуємо ім'я з ПОТОЧНОГО повідомлення
    current_user_name = get_user_display_name(message.from_user)
    
    current_time = time.time()
    
    try:
        bot_info = await bot.get_me()
    except Exception as e:
        logger.error(f"Не вдалося отримати інформацію про бота в handle_trigger_messages: {e}")
        return

    # --- 2. Визначення умов для відповіді (Рівні Пріоритету) ---
    is_explicit_mention = f"@{bot_info.username.lower()}" in text_lower
    is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
    is_name_mention = any(re.search(r'\b' + name + r'\b', text_lower) for name in BOT_NAMES)

    # --- 3. Пошук тригера ---
    matched_trigger_mood = None
    for trigger, mood in CONVERSATIONAL_TRIGGERS.items():
        if re.search(r'\b' + re.escape(trigger) + r'\b', text_lower):
            matched_trigger_mood = mood
            break
    
    if is_reply_to_bot and not matched_trigger_mood:
        matched_trigger_mood = "Користувач відповів на твоє повідомлення. Підтримай розмову."

    if not matched_trigger_mood:
        return

    # --- 4. Логіка прийняття фінального рішення про відповідь ---
    should_respond = False
    if is_explicit_mention or is_reply_to_bot or is_name_mention:
        should_respond = True
        logger.info(f"Прийнято рішення відповісти: пряме звернення в чаті {chat_id} від {current_user_name}.")
    else:
        last_response_time = chat_cooldowns.get(chat_id, 0)
        if (current_time - last_response_time) > CONVERSATIONAL_COOLDOWN_SECONDS:
            should_respond = True
            chat_cooldowns[chat_id] = current_time
            logger.info(f"Прийнято рішення відповісти: пасивний тригер в чаті {chat_id} від {current_user_name} (кулдаун пройшов).")
        else:
            logger.info(f"Рішення проігнорувати: пасивний тригер в чаті {chat_id} від {current_user_name} (активний кулдаун).")

    # --- 5. Генерація та відправка відповіді ---
    if should_respond:
        # Додаємо повідомлення користувача до історії з актуальним іменем
        chat_histories[chat_id].append({"role": "user", "content": message.text})
        
        try:
            history_for_api = list(chat_histories[chat_id])
            async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
                # 🎯 ПЕРЕДАЄМО АКТУАЛЬНЕ ІМ'Я В GPT
                reply_text = await gpt.generate_conversational_reply(
                    user_name=current_user_name,  # Тепер завжди актуальне ім'я!
                    chat_history=history_for_api,
                    trigger_mood=matched_trigger_mood
                )

            if reply_text and "<i>" not in reply_text:
                chat_histories[chat_id].append({"role": "assistant", "content": reply_text})
                await message.reply(reply_text)
                logger.info(f"Адаптивну відповідь успішно надіслано в чат {chat_id} для {current_user_name}.")
            else:
                logger.error(f"Сервіс повернув порожню або помилкову відповідь для чату {chat_id} користувача {current_user_name}.")
        except Exception as e:
            logger.exception(f"Критична помилка під час генерації адаптивної відповіді в чаті {chat_id} для {current_user_name}: {e}")


async def error_handler(event: types.ErrorEvent, bot: Bot):
    """
    Глобальний обробник помилок. Логує помилку та надсилає повідомлення користувачу.
    
    🔧 ПОКРАЩЕНИЙ: Більш детальна обробка різних типів помилок.
    """
    logger.error(
        f"Глобальна помилка: {event.exception} для update: {event.update.model_dump_json(exclude_none=True, indent=2)}",
        exc_info=event.exception
    )

    chat_id: Optional[int] = None
    user_name: str = "друже"

    update = event.update
    if update.message and update.message.chat:
        chat_id = update.message.chat.id
        user_name = get_user_display_name(update.message.from_user)  # Використовуємо безпечну функцію
    elif update.callback_query and update.callback_query.message and update.callback_query.message.chat:
        chat_id = update.callback_query.message.chat.id
        user_name = get_user_display_name(update.callback_query.from_user)  # Також тут
        try:
            await update.callback_query.answer("Сталася помилка...", show_alert=False)
        except TelegramAPIError:
            pass

    # Більш інформативні повідомлення залежно від типу помилки
    if "AttributeError" in str(event.exception) and "NoneType" in str(event.exception):
        error_message_text = f"Вибач, {user_name}, виникла технічна проблема з обробкою повідомлення 🔧\nВже виправляємо!"
    elif "TelegramAPIError" in str(event.exception):
        error_message_text = f"Упс, {user_name}, проблема з Telegram API 📡\nСпробуй ще раз через хвилинку."
    else:
        error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилинку."

    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except TelegramAPIError as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді користувачу.")


# === ФУНКЦІЯ РЕЄСТРАЦІЇ ОБРОБНИКІВ ===
def register_general_handlers(dp: Dispatcher):
    """
    Реєструє всі обробники в головному диспетчері.

    КЛЮЧОВА ЗМІНА: реєструє `party_router` ПЕРЕД `general_router`,
    щоб специфічна логіка паті мала вищий пріоритет.
    """
    dp.include_router(party_router)
    dp.include_router(general_router)
    logger.info("🚀 Обробники для паті (FSM), тригерів та 🆕 універсального Vision модуля успішно зареєстровано в правильному порядку.")
