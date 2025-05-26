#main.py 
"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.

Python 3.11+ | aiogram 3.19+ | OpenAI gpt-4.1 (або новіша)
Author: MLBB-BOSS | Date: 2025-05-26
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta # Додано timezone, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

# === НАЛАШТУВАННЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__) # Головний логер для модуля

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")


class MLBBChatGPT:
    """
    Спеціалізований GPT асистент для MLBB з персоналізацією.
    Відповіді структуруються, оформлюються для ідеального вигляду в Telegram.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        # Специфічний логер для цього класу для кращого відстеження
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=45), # Збільшено загальний таймаут
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("Aiohttp ClientSession створено.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("Aiohttp ClientSession закрито.")
        if exc_type:
            self.class_logger.error(f"Помилка в контекстному менеджері MLBBChatGPT: {exc_type} {exc_val}", exc_info=True)


    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """
        🚀 Оновлений ПРОМПТ v2.2 - Баланс конкретики та природності.
        """
        # Визначення часу за Києвом для коректного привітання
        kyiv_tz = timezone(timedelta(hours=3))  # UTC+3
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour

        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

        # Промпт v2.2
        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.2 🎮

## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, AI-експерт Mobile Legends Bang Bang з багаторічним досвідом.
Твоя місія: надавати гравцю {user_name} максимально корисні, точні, конкретні та мотивуючі відповіді українською мовою. Спілкуйся природно та дружньо.

## КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
- Платформа: Telegram (підтримує HTML, тому ВАЖЛИВО генерувати ВАЛІДНИЙ HTML з коректно закритими тегами <b>, <i>, <code>).

## СТАНДАРТИ ЯКОСТІ ВІДПОВІДЕЙ

### 🎯 СТРУКТУРА ТА ЗМІСТ:
1.  **Привітання**: "{greeting}, {user_name}! 👋"
2.  **Основна відповідь**:
    *   Конкретна інформація по суті запиту.
    *   Якщо запит стосується вибору героїв, стратегій, ролей або гри на певній лінії (наприклад, "як грати на експ лінії", "порадь героя для міду"), ОБОВ'ЯЗКОВО запропонуй 2-3 актуальних героїв.
    *   Коротко поясни, чому ці герої є хорошим вибором (їхні ключові переваги, роль).
    *   Якщо доречно, згадай про можливі ефективні комбінації або синергію з іншими героями.
3.  **Практичні поради**: Кілька дієвих порад, що робити гравцю.
4.  **Мотивація**: Позитивне та підбадьорююче завершення.

### 📝 ФОРМАТУВАННЯ (ВАЛІДНИЙ HTML):
-   Використовуй ТІЛЬКИ HTML теги: <b>для жирного</b>, <i>для курсиву</i>, <code>для коду/назв</code>. УСІ ТЕГИ ПОВИННІ БУТИ КОРЕКТНО ЗАКРИТІ.
-   Списки оформлюй через "• " (з пробілом після маркера).
-   Відповідь має бути структурованою, легкою для читання, приблизно 200-300 слів.
-   Використовуй доречні емодзі для покращення сприйняття (наприклад, 🦸‍♂️ для героїв, 💡 для порад, 🤝 для комбо).

### 🎮 ЕКСПЕРТИЗА MLBB:
-   **Герої**: Знання механік, ролей, актуальних контрпіків, сильних героїв для поточної мети. Завжди пропонуй конкретні приклади героїв, коли це доречно.
-   **Стратегії**: Розуміння лейн-менеджменту, контролю об'єктів, тімфайт-тактик, макро-гри.
-   **Ранкінг та Психологія**: Поради щодо підняття рангу, комунікації, контролю тільту.
-   **Поточний патч**: Намагайся враховувати актуальні тренди та зміни в грі.

### ❌ УНИКАЙ:
-   Markdown форматування.
-   НЕЗАКРИТИХ або некоректних HTML тегів (це спричиняє помилки відображення).
-   Надто детальних білдів (предмети/емблеми), оскільки вони швидко застарівають. Краще фокусуйся на стилі гри.
-   Довгих, монотонних блоків тексту.

## ПРИКЛАД СТИЛЮ ТА СТРУКТУРИ ВІДПОВІДІ (на запит "як грати на експ лінії"):
"{greeting}, {user_name}! 👋

Гра на експ лінії дійсно важлива для стабільності команди! 🛡️

🦸‍♂️ <b>Ось декілька сильних героїв для експ лінії зараз:</b>
• <b>Ю Чжун:</b> Чудовий для домінації 1на1 завдяки відхілу та сильному ультімейту для бійок. <i>Агресивний вибір.</i>
• <b>Аралотт:</b> Має багато контролю та мобільності, ефективний проти багатьох мета-героїв. <i>Гарний для командних сутичок.</i>
• <b>Едіт:</b> Унікальний танк/стрілець, що може адаптуватися під ситуацію, сильна в лейті. <i>Гнучкий вибір.</i>

💡 <b>Ключові поради для експ-лейнера:</b>
• Фокусуйся на отриманні 4-го рівня для розблокування ультімейту.
• Слідкуй за картою, допомагай команді з Черепахою/Лордом.
• Не бійся розмінюватися здоров'ям, якщо це вигідно для команди.

🤝 <b>Щодо комбо:</b> Герої як <i>Ю Чжун</i> чи <i>Аралотт</i> чудово працюють з ініціаторами типу <i>Атлас</i> або <i>Лоліта</i>, які збирають ворогів для їхніх атак.

Пам'ятай, вибір героя залежить від піку твоєї команди та ворогів. Експериментуй та знаходь свій стиль! Вперед до перемог! 🚀"

## ЗАПИТ ВІД {user_name}: "{user_query}"

Твоя експертна відповідь (дотримуйся стандартів вище, особливо щодо ВАЛІДНОГО HTML та надання прикладів героїв, де це доречно):"""

    def _beautify_response(self, text: str) -> str:
        """
        Оформлює текст GPT для Telegram: замінює markdown/заголовки, додає емодзі, відступи
        та намагається виправити незбалансовані теги <b>.
        """
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍", "комунікація": "💬",
            "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄", "командна гра": "🤝",
            "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", "стратегі": "🎯", "мета": "🔥",
            "поточна мета": "📊", "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "💡"
        }

        def replace_header(match):
            header_text = match.group(1).strip(": ").capitalize()
            best_emoji = "💡" # Default
            # Пріоритет для більш специфічних ключів
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета"]
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else: # Якщо не знайдено, шукаємо серед загальних
                for key, emj in header_emojis.items():
                    if key in header_text.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>:"

        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\*\*(.+?)\*\*[:\s]*", replace_header, text, flags=re.MULTILINE)
        
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+-\s+", "  ◦ ", text, flags=re.MULTILINE) 
        
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Заміна Markdown на HTML, якщо GPT їх все ж використає
        text = re.sub(r"\*\*(?P<content>.+?)\*\*", r"<b>\g<content></b>", text)
        text = re.sub(r"\*(?P<content>.+?)\*", r"<i>\g<content></i>", text)
        
        open_b_count = len(re.findall(r"<b>", text))
        close_b_count = len(re.findall(r"</b>", text))

        if open_b_count > close_b_count:
            missing_tags = open_b_count - close_b_count
            self.class_logger.warning(f"Beautify: Виявлено {missing_tags} незакритих тегів <b>. Додаю їх в кінець.")
            text += "</b>" * missing_tags
        elif close_b_count > open_b_count:
            self.class_logger.warning(f"Beautify: Виявлено {close_b_count - open_b_count} зайвих тегів </b>.")

        self.class_logger.debug(f"Beautify: Текст після обробки (перші 100 символів): '{text[:100]}'")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Отримує якісну відповідь від GPT і оформлює її для Telegram.
        """
        self.class_logger.info(f"Запит до GPT від '{user_name}': '{user_query}'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4.1", # Рекомендовано, або "gpt-4.1", "gpt-4"
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000, 
            "temperature": 0.65, # Збільшимо трохи для більш природних відповідей
            "top_p": 0.9,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2
        }

        try:
            async with self.session.post( # type: ignore
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка: {response.status} - {error_text}")
                    return f"Вибач, {user_name}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status}). Спробуй, будь ласка, повторити запит трохи пізніше!"

                result = await response.json()
                
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка: несподівана структура відповіді - {result}")
                    return f"Вибач, {user_name}, ШІ повернув несподівану відповідь 🤯. Спробуй переформулювати запит."

                raw_gpt_text = result["choices"][0]["message"]["content"]
                self.class_logger.info(f"Сира відповідь від GPT (перші 100 символів): '{raw_gpt_text[:100]}'")
                
                beautified_text = self._beautify_response(raw_gpt_text)
                return beautified_text

        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout помилка для запиту: '{user_query}'")
            return f"Вибач, {user_name}, запит до ШІ зайняв занадто багато часу ⏳. Спробуй ще раз!"
        except Exception as e:
            self.class_logger.exception(f"Загальна GPT помилка під час обробки запиту '{user_query}': {e}")
            return f"Не вдалося обробити твій запит, {user_name} 😕 Спробуй, будь ласка, пізніше!"


bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Обробник команди /start, вітає користувача."""
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    logger.info(f"Користувач {user_name} (ID: {user_id}) запустив бота командою /start.")
    
    kyiv_tz = timezone(timedelta(hours=3))
    current_time_kyiv = datetime.now(kyiv_tz)
    current_hour = current_time_kyiv.hour

    greeting_msg = "Доброго ранку" if 5 <= current_hour < 12 else \
                   "Доброго дня" if 12 <= current_hour < 17 else \
                   "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
    emoji = "🌅" if 5 <= current_hour < 12 else \
            "☀️" if 12 <= current_hour < 17 else \
            "🌆" if 17 <= current_hour < 22 else "🌙"

    welcome_text = f"""
{greeting_msg}, <b>{user_name}</b>! {emoji}

🎮 Вітаю в MLBB IUI mini v2.2!

Я - твій персональний AI-експерт по Mobile Legends Bang Bang, готовий допомогти з будь-якими питаннями, надаючи конкретні поради та приклади героїв!

<b>💡 Як користуватися:</b>
Просто напиши своє питання після команди /go

<b>🚀 Приклади запитів:</b>
• <code>/go як грати на експ лінії проти бійців</code>
• <code>/go порадь сильних магів для підняття рангу соло</code>
• <code>/go найкращі комбінації героїв для командних боїв 5на5</code>

<b>🔥 Покращення v2.2:</b>
• Збалансований промпт для більш природних та конкретних відповідей.
• Акцент на актуальній меті та синергії героїв.
• Покращена обробка помилок форматування HTML.

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    try:
        await message.answer(welcome_text)
        logger.info(f"Привітання для {user_name} (v2.2) надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітання для {user_name}: {e}")


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """Обробник команди /go, взаємодія з GPT."""
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name} (ID: {user_id}) зробив запит з /go: '{user_query}'")

    if not user_query:
        logger.info(f"Порожній запит від {user_name}. Надсилаю підказку.")
        await message.reply(
            f"Привіт, <b>{user_name}</b>! 👋\n\n"
            "Напиши своє питання після /go, і я спробую дати конкретні поради з прикладами героїв!\n"
            "<b>Приклади:</b>\n"
            "• /go стратегії для швидкого ранк-апу на стрільцях\n"
            "• /go яких героїв обрати для домінації на міді"
        )
        return

    thinking_messages = [
        f"🤔 {user_name}, аналізую твій запит та підбираю героїв...",
        f"🧠 Обробляю інформацію, {user_name}, щоб дати кращі поради!",
        f"⚡ Готую експертну відповідь з прикладами спеціально для тебе!",
        f"🎯 {user_name}, шукаю найефективніших героїв та стратегії для тебе!"
    ]
    thinking_msg_text = thinking_messages[int(time.time()) % len(thinking_messages)]
    
    thinking_msg: Optional[Message] = None
    try:
        thinking_msg = await message.reply(thinking_msg_text)
    except Exception as e:
        logger.error(f"Не вдалося надіслати 'thinking_msg' для {user_name}: {e}")

    start_time = time.time()
    response_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"

    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка при виклику MLBBChatGPT для запиту '{user_query}' від {user_name}: {e}")
        # response_text вже має значення за замовчуванням

    processing_time = time.time() - start_time
    logger.info(f"Час обробки запиту GPT для '{user_query}' від {user_name}: {processing_time:.2f}с")

    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.2 GPT</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        target_message = thinking_msg if thinking_msg else message
        if thinking_msg:
            await thinking_msg.edit_text(full_response_to_send)
        else:
            await message.reply(full_response_to_send)
        logger.info(f"Відповідь для {user_name} (ID: {user_id}) успішно надіслано/відредаговано.")
    except TelegramAPIError as e:
        logger.error(f"Telegram API помилка при надсиланні/редагуванні для {user_name}: {e}. Текст (перші 100): '{full_response_to_send[:100]}'")
        if "can't parse entities" in str(e).lower():
            logger.error(f"ПОМИЛКА РОЗБОРУ HTML для '{user_query}'. Текст, що спричинив помилку (перші 200): '{response_text[:200]}'")
            plain_text_response = re.sub(r"<[^>]+>", "", response_text) 
            fallback_message = (
                f"{plain_text_response}{admin_info}\n\n"
                f"<i>(Вибач, виникла помилка форматування HTML. Відповідь показано як простий текст. "
                f"Спробуй переформулювати запит.)</i>"
            )
            try:
                if thinking_msg:
                    await thinking_msg.edit_text(fallback_message, parse_mode=None)
                else:
                    await message.reply(fallback_message, parse_mode=None)
                logger.info(f"Відповідь для {user_name} надіслано як простий текст після помилки HTML.")
            except Exception as plain_text_e:
                logger.error(f"Не вдалося надіслати навіть простий текст для {user_name} після помилки HTML: {plain_text_e}")
                final_fallback_text = f"Вибач, {user_name}, сталася помилка відображення відповіді. Спробуй ще раз."
                try:
                    if thinking_msg: await thinking_msg.edit_text(final_fallback_text, parse_mode=None)
                    else: await message.reply(final_fallback_text, parse_mode=None)
                except Exception as ff_e:
                    logger.error(f"Помилка надсилання фінального fallback повідомлення: {ff_e}")
        else:
            # Інші помилки TelegramAPIError
            logger.error(f"Інша помилка TelegramAPIError для {user_name}: {e}")
            try:
                await message.reply(f"Вибач, {user_name}, сталася помилка при відправці відповіді. Спробуй пізніше. (Код: TG_{e.__class__.__name__})", parse_mode=None)
            except Exception as final_e:
                 logger.error(f"Не вдалося надіслати повідомлення про іншу помилку Telegram для {user_name}: {final_e}")


@dp.errors()
async def error_handler(update_event, exception: Exception):
    """Глобальний обробник помилок."""
    logger.error(f"Глобальна помилка в error_handler: {exception} для update: {update_event}", exc_info=True)
    
    chat_id = None
    user_name = "друже"

    if hasattr(update_event, 'message') and update_event.message:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = update_event.message.from_user.first_name
    elif hasattr(update_event, 'callback_query') and update_event.callback_query:
        chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = update_event.callback_query.from_user.first_name
            try: # Відповідаємо на callback, щоб він не "завис"
                await update_event.callback_query.answer("Сталася помилка...", show_alert=False)
            except Exception: pass # Ігноруємо помилки тут
    
    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину!"
    
    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку користувачу {user_name} в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді.")


async def main() -> None:
    """Головна функція для запуску бота."""
    logger.info(f"🚀 Запуск MLBB IUI mini v2.2... (PID: {os.getpid()})")

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований та готовий!")

        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini v2.2 запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Промпт v2.2 активний (збалансований)!</b>\n"
                    f"🟢 Готовий до роботи!"
                )
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}")
        
        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt).")
    except TelegramAPIError as e:
        logger.critical(f"Критична помилка Telegram API під час запуску або роботи: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"Непередбачена критична помилка під час запуску або роботи: {e}", exc_info=True)
    finally:
        logger.info("🛑 Розпочинаю процес зупинки бота та закриття сесій...")
        if bot.session and not bot.session.closed: # type: ignore
            await bot.session.close() # type: ignore
            logger.info("Сесію HTTP клієнта бота закрито.")
        logger.info("👋 Бот остаточно зупинено.")


if __name__ == "__main__":
    asyncio.run(main())
