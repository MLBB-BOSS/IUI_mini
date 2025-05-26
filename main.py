"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.

Python 3.11+ | aiogram 3.19+ | OpenAI gpt-4.1
Author: MLBB-BOSS | Date: 2025-05-26
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
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
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s" # Додано %(name)s для кращого розрізнення логів
)
logger = logging.getLogger(__name__)

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
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}") # Специфічний логер для класу

    async def __aenter__(self):
        # Створюємо сесію тут, щоб вона була свіжою для кожного контексту `async with`
        self.session = ClientSession(
            timeout=ClientTimeout(total=45), # Збільшено таймаут
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.logger.debug("ClientSession створено")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug("ClientSession закрито")
        if exc_type:
            self.logger.error(f"Помилка в контекстному менеджері MLBBChatGPT: {exc_type} {exc_val}")

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """
        🚀 РЕВОЛЮЦІЙНИЙ ПРОМПТ v2.1 - Акцент на конкретних героях та комбо!
        """
        kyiv_tz = timezone(timedelta(hours=3))
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour

        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.1 🎮

## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, найкращий AI-експерт Mobile Legends Bang Bang в Україні з 7+ років досвіду.
Твоя місія: надавати гравцю {user_name} максимально корисні, точні, конкретні та мотивуючі відповіді. Генеруй ТІЛЬКИ ВАЛІДНИЙ HTML. Кожен тег <b> повинен мати відповідний </b>.

## КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
- Платформа: Telegram (підтримує HTML, тому ВСІ теги мають бути коректно закриті)
- Мова: виключно українська

## СТАНДАРТИ ЯКОСТІ ВІДПОВІДЕЙ

### 🎯 ОБОВ'ЯЗКОВА СТРУКТУРА:
1. **Привітання**: "{greeting}, {user_name}! 👋"
2. **Основна відповідь**: конкретна інформація. 
   - Якщо запит стосується стратегій, ролей, вибору героїв або гри на певній лінії, ОБОВ'ЯЗКОВО наведи 2-3 приклади актуальних героїв (наприклад, 🦸‍♂️ <b>Ю Чжун</b>, 🦸‍♀️ <b>Есмеральда</b>). 
   - Коротко поясни, чому саме ці герої підходять для описаної ситуації.
   - За можливості, запропонуй ефективні комбінації.
3. **Практичні поради**: що робити прямо зараз.
4. **Мотивація**: підбадьорення до дій.

### 📝 ФОРМАТУВАННЯ:
- Використовуй ТІЛЬКИ HTML теги: <b>жирний текст</b>, <i>курсив</i>, <code>код</code>. ЗАВЖДИ ЗАКРИВАЙ ТЕГИ.
- Списки через "•" (з пробілом після).
- Максимум 250-300 слів.
- Обов'язкові емодзі (🦸‍♂️, 💡, 🤝).

### 🎮 ЕКСПЕРТИЗА MLBB:
- **Герої**: механіки, ролі, контрпіки, мета. ЗАВЖДИ пропонуй приклади героїв.
- **Стратегії**: лейн-менеджмент, об'єкти, тімфайти.
- **Ранкінг**: тактики, адаптація.
- **Психологія**: комунікація, тільт-контроль.
- **Поточний патч**: враховуй тренди.

### ❌ ЗАБОРОНЕНО:
- Markdown форматування.
- НЕЗАКРИТІ HTML ТЕГИ (наприклад, `<b>текст` без `</b>`). Це спричиняє помилки.
- Конкретні білди (предмети/емблеми).
- Довгі суцільні тексти.
- Відповіді не українською.

### 🧠 ПРИНЦИПИ МИСЛЕННЯ:
1. **Аналізуй запит**.
2. **Конкретика**: конкретні герої та поради.
3. **Практичність**.
4. **Адаптивність**.
5. **Позитивність**.
6. **ВАЛІДНИЙ HTML**: Переконайся, що всі теги <b>, <i>, <code> правильно закриті.

## ПРИКЛАД ІДЕАЛЬНОЇ ВІДПОВІДІ (на запит "як грати на експ лінії"):
"{greeting}, {user_name}! 👋

Гра на експ лінії – це твій шанс стати опорою команди! 🛡️

🦸‍♂️ <b>Рекомендовані герої для експ лінії:</b>
• <b>Ю Чжун:</b> Дуже сильний в 1на1. <i>Ідеальний для агресії.</i>
• <b>Есмеральда:</b> Неймовірна виживаність. <i>Чудовий вибір проти щитів.</i>

💡 <b>Ключові поради:</b>
• <b>Пріоритет на фарм.</b>
• <b>Контроль карти.</b>

🤝 <b>Приклад синергії:</b>
Якщо у команді є <i>Атлас</i>, герої як <i>Ю Чжун</i> можуть реалізувати потенціал.

<b>Твій успіх</b> – це поєднання терпіння та розуміння. Готовий домінувати? 🚀"

## ЗАПИТ ВІД {user_name}: "{user_query}"

Твоя експертна відповідь (ВАЖЛИВО: дотримуйся ВСІХ стандартів, особливо щодо ВАЛІДНОГО HTML та закриття тегів <b>, <i>, <code>):"""

    def _beautify_response(self, text: str) -> str:
        """
        Оформлює текст GPT для Telegram: замінює markdown/заголовки, додає емодзі, відступи
        та намагається виправити незбалансовані теги <b>.
        """
        self.logger.debug(f"Початковий текст для beautify (перші 300 символів): {text[:300]}")
        # Емодзі для різних категорій MLBB
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍",
            "комунікація": "💬", "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄",
            "командна гра": "🤝", "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", 
            "стратегі": "🎯", "мета": "🔥", "поточна мета": "📊",
            "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "💡"
        }

        def replace_header(match):
            header_text = match.group(1).strip(": ").capitalize()
            best_emoji = "💡"
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета"]
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else:
                for key, emj in header_emojis.items():
                    if key in header_text.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>:"

        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\*\*(.+?)\*\*[:\s]*", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^<b>(.+?)</b>[:\s]*", lambda m: replace_header(m) if ':' in m.group(0) else m.group(0), text, flags=re.MULTILINE)
        
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+-\s+", "  ◦ ", text, flags=re.MULTILINE)
        
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text) # Заміна Markdown **bold** на <b>bold</b>
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)     # Заміна Markdown *italic* на <i>italic</i>
        
        # Спроба виправити незбалансовані теги <b>
        open_b_count = text.count("<b>")
        close_b_count = text.count("</b>")

        if open_b_count > close_b_count:
            missing_closing_tags = open_b_count - close_b_count
            self.logger.warning(
                f"Виявлено {missing_closing_tags} незакритих тегів <b>. "
                f"Додаю їх в кінець тексту. Початковий текст (перші 300): {text[:300]}"
            )
            text += "</b>" * missing_closing_tags
        elif close_b_count > open_b_count:
            # Ця ситуація менш імовірна для помилки "Can't find end tag"
            self.logger.warning(
                f"Виявлено {close_b_count - open_b_count} зайвих тегів </b>. "
                f"Це може спричинити проблеми. Початковий текст (перші 300): {text[:300]}"
            )
            # Наразі не робимо автоматичних виправлень для зайвих </b>, оскільки це складніше

        self.logger.debug(f"Текст після beautify (перші 300 символів): {text[:300]}")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Отримує якісну відповідь від GPT і оформлює її для Telegram.
        """
        self.logger.info(f"Запит до GPT від {user_name}: '{user_query}'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4-turbo", # Або інша доступна модель
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000,
            "temperature": 0.65,
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.15
        }

        try:
            if not self.session or self.session.closed:
                self.logger.warning("Aiohttp сесія була закрита або відсутня. Перестворюю.")
                # Цей блок тут для безпеки, але __aenter__ має керувати створенням
                self.session = ClientSession( 
                    timeout=ClientTimeout(total=45),
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )

            async with self.session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.logger.error(f"OpenAI API помилка: {response.status} - {error_text}")
                    return f"Вибач, {user_name}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status}). Спробуй, будь ласка, повторити запит трохи пізніше!"

                result = await response.json()
                
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.logger.error(f"OpenAI API помилка: несподівана структура відповіді - {result}")
                    return f"Вибач, {user_name}, ШІ повернув несподівану відповідь 🤯. Спробуй переформулювати запит."

                raw_gpt_text = result["choices"][0]["message"]["content"]
                self.logger.info(f"Сира відповідь від GPT (перші 300 символів): {raw_gpt_text[:300]}")
                
                beautified_text = self._beautify_response(raw_gpt_text)
                return beautified_text

        except asyncio.TimeoutError:
            self.logger.error(f"OpenAI API Timeout помилка для запиту: {user_query}")
            return f"Вибач, {user_name}, запит до ШІ зайняв занадто багато часу ⏳. Спробуй ще раз!"
        except Exception as e:
            self.logger.exception(f"Загальна GPT помилка під час обробки запиту '{user_query}': {e}")
            return f"Не вдалося обробити твій запит, {user_name} 😕 Спробуй, будь ласка, пізніше!"


bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Просте та ефективне привітання."""
    user_name = message.from_user.first_name
    logger.info(f"Користувач {user_name} (ID: {message.from_user.id}) запустив бота командою /start")
    
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

🎮 Вітаю в MLBB IUI mini v2.1!

Я - твій персональний експерт по Mobile Legends Bang Bang, готовий допомогти з будь-якими питаннями про гру, надаючи конкретні поради та приклади героїв!

<b>💡 Як користуватися:</b>
Просто напиши своє питання після команди /go

<b>🚀 Приклади запитів:</b>
• <code>/go як грати на експ лінії проти бійців</code>
• <code>/go порадь сильних магів для підняття рангу соло</code>
• <code>/go найкращі комбінації героїв для командних боїв 5на5</code>
• <code>/go як ефективно контролювати карту та об'єкти граючи за лісника</code>

<b>🔥 Покращення v2.1:</b>
• Відповіді тепер включають конкретні приклади героїв!
• Поради стали більш практичними та менш "сухими".
• Акцент на актуальній меті та синергії героїв.
• Покращена обробка помилок форматування.

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    await message.answer(welcome_text)
    logger.info(f"✅ Привітання для {user_name} (v2.1) надіслано.")


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """Головна функція - якісне спілкування через GPT з красивим оформленням."""
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    user_query = message.text.replace("/go", "", 1).strip()

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
    # Використовуємо модуль для більш рівномірного розподілу
    thinking_msg_text = thinking_messages[int(time.time()) % len(thinking_messages)]
    
    try:
        thinking_msg = await message.reply(thinking_msg_text)
    except Exception as e:
        logger.error(f"Не вдалося надіслати 'thinking_msg' для {user_name}: {e}")
        # Продовжуємо без thinking_msg, якщо не вдалося
        thinking_msg = None


    start_time = time.time()
    response_text = "" # Ініціалізуємо змінну

    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка при виклику MLBBChatGPT для запиту '{user_query}': {e}")
        response_text = f"Вибач, {user_name}, сталася серйозна помилка під час генерації відповіді. Розробники вже сповіщені."


    processing_time = time.time() - start_time
    logger.info(f"Час обробки запиту GPT для '{user_query}': {processing_time:.2f}с")

    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.1 Enhanced GPT-4T</i>"
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        if thinking_msg:
            await thinking_msg.edit_text(full_response_to_send)
        else: # Якщо thinking_msg не було створено
            await message.reply(full_response_to_send)
        logger.info(f"📤 Відповідь для {user_name} (ID: {user_id}) успішно надіслано/відредаговано. Запит: '{user_query}'")
    except TelegramAPIError as e:
        logger.error(f"Telegram API помилка при редагуванні/надсиланні повідомлення для {user_name}: {e}. Повідомлення (перші 300): '{full_response_to_send[:300]}'")
        if "can't parse entities" in str(e).lower():
            logger.error(f"ПОМИЛКА РОЗБОРУ HTML для запиту '{user_query}'. Текст, що спричинив помилку (перші 500): {response_text[:500]}")
            plain_text_response = re.sub(r"<[^>]+>", "", response_text) # Видаляємо всі HTML теги
            fallback_message = (
                f"{plain_text_response}{admin_info}\n\n"
                f"<i>(Виникла помилка форматування HTML. Показано як простий текст. "
                f"Спробуйте переформулювати запит або зверніться до підтримки, якщо проблема повторюється.)</i>"
            )
            try:
                if thinking_msg: # Спробуємо відредагувати thinking_msg на простий текст
                    await thinking_msg.edit_text(fallback_message, parse_mode=None) # parse_mode=None для простого тексту
                else: # Або надішлемо нове повідомлення
                    await message.reply(fallback_message, parse_mode=None)
                logger.info(f"📤 Відповідь для {user_name} надіслано як простий текст після помилки HTML.")
            except Exception as plain_text_e:
                logger.error(f"Не вдалося надіслати навіть простий текст для {user_name} після помилки HTML: {plain_text_e}")
                # Якщо і це не вдалося, надсилаємо максимально просте повідомлення
                final_fallback_text = f"Вибач, {user_name}, сталася помилка відображення відповіді. Спробуй ще раз."
                if thinking_msg: await thinking_msg.edit_text(final_fallback_text, parse_mode=None)
                else: await message.reply(final_fallback_text, parse_mode=None)
        else:
            # Для інших помилок TelegramAPIError, спробуємо просто надіслати як нове повідомлення (якщо редагування не вдалося)
            try:
                await message.reply(full_response_to_send) # Це може знову спричинити помилку, якщо проблема та сама
                logger.info(f"📤 Відповідь для {user_name} надіслано новим повідомленням після помилки редагування (не пов'язаної з HTML).")
            except Exception as final_e:
                logger.error(f"Не вдалося надіслати відповідь для {user_name} навіть новим повідомленням: {final_e}")
                final_fallback_text = f"Вибач, {user_name}, не вдалося відобразити відповідь. Спробуй ще раз."
                if thinking_msg: await thinking_msg.edit_text(final_fallback_text, parse_mode=None)
                else: await message.reply(final_fallback_text, parse_mode=None)


@dp.errors()
async def error_handler(update_event, exception: Exception):
    logger.error(f"🚨 Загальна помилка в обробнику помилок: {exception} для update: {update_event}", exc_info=True)
    
    chat_id = None
    user_name = "друже"

    if hasattr(update_event, 'message') and update_event.message:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = update_event.message.from_user.first_name
    elif hasattr(update_event, 'callback_query') and update_event.callback_query:
        # Якщо у вас є callback_query, обробка може бути іншою
        chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = update_event.callback_query.from_user.first_name
            # Можливо, потрібно відповісти на callback_query
            # await update_event.callback_query.answer("Сталася помилка...", show_alert=True)
    
    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину!"
    
    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None) # parse_mode=None для безпеки
        except Exception as e:
            logger.error(f"🚨 Не вдалося надіслати повідомлення про системну помилку користувачу {user_name} в чат {chat_id}: {e}")
    else:
        logger.warning("🚨 Системна помилка сталася, але не вдалося визначити chat_id для відповіді.")


async def main() -> None:
    """Запуск бота."""
    logger.info(f"🚀 Запуск MLBB IUI mini v2.1... (PID: {os.getpid()})")

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований та готовий!")

        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini v2.1 запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Промпт v2.1 активний (з акцентом на героях та виправленням HTML)!</b>\n"
                    f"🟢 Готовий до роботи!"
                )
                logger.info(f"ℹ️ Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}")
        
        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt)")
    except TelegramAPIError as e:
        logger.critical(f"💥 Критична помилка Telegram API під час запуску або роботи: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"💥 Непередбачена критична помилка під час запуску або роботи: {e}", exc_info=True)
    finally:
        logger.info("🛑 Розпочинаю процес зупинки бота та закриття сесій...")
        if bot.session and not bot.session.closed:
            await bot.session.close()
            logger.info("Сесію HTTP клієнта бота закрито.")
        # Якщо Dispatcher створює власну сесію або ресурси, вони мають бути звільнені тут,
        # але зазвичай aiogram керує цим автоматично при завершенні start_polling.
        logger.info("👋 Бот остаточно зупинено.")


if __name__ == "__main__":
    # Встановлення більш детального рівня логування для розробки (можна змінити на INFO для продакшену)
    # logging.getLogger('aiogram').setLevel(logging.DEBUG) 
    # logging.getLogger('aiohttp').setLevel(logging.DEBUG)
    asyncio.run(main())
