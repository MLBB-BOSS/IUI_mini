# топ віжен варіант
"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано функціонал аналізу скріншотів профілю гравця з "вау-ефектом" та описом від ШІ.
Моделі GPT жорстко встановлені в коді для аналізу та опису.

Python 3.11+ | aiogram 3.19+ | OpenAI
Author: MLBB-BOSS | Date: 2025-05-29
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import base64
import json
import html

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
import aiohttp
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# === НАЛАШТУВАННЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

WELCOME_IMAGE_URL: str = "https://res.cloudinary.com/ha1pzppgf/image/upload/v1748286434/file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

logger.info(f"Модель для Vision (аналіз скріншотів): gpt-4o-mini (жорстко задано)")
logger.info(f"Модель для текстових генерацій (/go, опис профілю): gpt-4.1 (жорстко задано)")

MAX_TELEGRAM_MESSAGE_LENGTH = 4090 # Трохи менше за офіційний ліміт 4096 для безпеки

async def send_message_in_chunks(
    bot_instance: Bot,
    chat_id: int,
    text: str,
    parse_mode: Optional[str],
    initial_message_to_edit: Optional[Message] = None
):
    """
    Надсилає повідомлення, розбиваючи його на частини, якщо воно занадто довге.
    Редагує initial_message_to_edit першою частиною, якщо надано,
    надсилає наступні частини як нові повідомлення.
    """
    if not text.strip():
        if initial_message_to_edit:
            try:
                await initial_message_to_edit.delete()
                logger.info(f"Видалено thinking_msg для chat_id {chat_id}, оскільки текст порожній.")
            except TelegramAPIError:
                pass # Ігноруємо, якщо не вдалося видалити
        return

    current_pos = 0
    processed_initial_message = False

    if initial_message_to_edit:
        first_chunk_text = text[:MAX_TELEGRAM_MESSAGE_LENGTH]
        if len(text) > MAX_TELEGRAM_MESSAGE_LENGTH:
            split_point = text.rfind('\n', 0, MAX_TELEGRAM_MESSAGE_LENGTH)
            if split_point != -1 and split_point > current_pos: # Ensure split_point is valid and after current_pos
                first_chunk_text = text[:split_point + 1]

        if first_chunk_text.strip():
            try:
                await initial_message_to_edit.edit_text(first_chunk_text, parse_mode=parse_mode)
                logger.info(f"Відредаговано initial_message_to_edit для chat_id {chat_id}. Довжина частини: {len(first_chunk_text)}")
                current_pos = len(first_chunk_text)
                processed_initial_message = True
            except TelegramAPIError as e:
                logger.warning(f"Не вдалося відредагувати initial_message_to_edit для chat_id {chat_id}: {e}. Повідомлення буде надіслано частинами.")
                try:
                    await initial_message_to_edit.delete()
                except TelegramAPIError:
                    pass
                # Do not set processed_initial_message to True here if deletion failed,
                # or rather, the logic will proceed to send as new message.
                # Let's consider it processed (attempted edit/delete) to avoid re-processing logic.
                processed_initial_message = True # Mark as processed (attempted edit/delete)
        else:
             try:
                await initial_message_to_edit.delete()
                logger.info(f"Видалено thinking_msg для chat_id {chat_id}, оскільки перша частина порожня.")
             except TelegramAPIError: pass
             processed_initial_message = True


    while current_pos < len(text):
        remaining_text_length = len(text) - current_pos
        chunk_size_to_cut = min(MAX_TELEGRAM_MESSAGE_LENGTH, remaining_text_length)

        actual_chunk_size = chunk_size_to_cut
        if chunk_size_to_cut < remaining_text_length: # If it's not the last part
            # Try to split at the last newline within the chunk_size_to_cut
            split_point = text.rfind('\n', current_pos, current_pos + chunk_size_to_cut)
            if split_point != -1 and split_point > current_pos: # Ensure split_point is valid
                actual_chunk_size = (split_point - current_pos) + 1
            # Else, if no '\n', or split_point is not useful, cut by MAX_TELEGRAM_MESSAGE_LENGTH

        chunk = text[current_pos : current_pos + actual_chunk_size]
        current_pos += actual_chunk_size

        if not chunk.strip():
            continue

        try:
            # If this is the first chunk to be sent (because initial_message_to_edit was None or edit failed and it was deleted)
            if not processed_initial_message and initial_message_to_edit is None:
                 # This case should ideally not happen if initial_message_to_edit logic is robust.
                 # However, if it does, we send a new message.
                 await bot_instance.send_message(chat_id, chunk, parse_mode=parse_mode)
                 processed_initial_message = True # Mark that we've started sending.
            else:
                 await bot_instance.send_message(chat_id, chunk, parse_mode=parse_mode)

            logger.info(f"Надіслано частину повідомлення для chat_id {chat_id}. Довжина: {len(chunk)}")
        except TelegramAPIError as e:
            logger.error(f"Telegram API помилка при надсиланні частини для chat_id {chat_id}: {e}. Частина (100): {html.escape(chunk[:100])}")
            if "can't parse entities" in str(e).lower() or "unclosed" in str(e).lower() or "expected" in str(e).lower():
                plain_chunk = re.sub(r"<[^>]+>", "", chunk) # Basic tag stripping
                if plain_chunk.strip():
                    try:
                        await bot_instance.send_message(chat_id, plain_chunk, parse_mode=None)
                        logger.info(f"Надіслано частину повідомлення як простий текст для chat_id {chat_id}. Довжина: {len(plain_chunk)}")
                        continue
                    except TelegramAPIError as plain_e:
                        logger.error(f"Не вдалося надіслати частину як простий текст для chat_id {chat_id}: {plain_e}")
            break

# === СТАНИ FSM ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===
class VisionAnalysisStates(StatesGroup):
    awaiting_profile_screenshot = State()
    awaiting_analysis_trigger = State()

# === ПРОМПТИ ===
PROFILE_SCREENSHOT_PROMPT = """
Ти — експертний аналітик гри Mobile Legends: Bang Bang.
Твоє завдання — уважно проаналізувати наданий скріншот профілю гравця.
Витягни наступну інформацію та поверни її ВИКЛЮЧНО у форматі валідного JSON об'єкта.
Не додавай жодного тексту до або після JSON, тільки сам JSON.

Структура JSON повинна бути такою:
{
  "game_nickname": "string або null, якщо не видно",
  "mlbb_id_server": "string у форматі 'ID (SERVER)' або null, якщо не видно (наприклад, '123456789 (1234)')",
  "highest_rank_season": "string (наприклад, 'Міфічна Слава 267 ★', 'Міфічна Слава 1111 ★') або null",
  "matches_played": "int або null",
  "likes_received": "int або null",
  "location": "string (наприклад, 'Ukraine/Dnipropetrovs'k') або null",
  "squad_name": "string (наприклад, 'IS Iron Spirit.') або null"
}

КРИТИЧНО ВАЖЛИВІ ІНСТРУКЦІЇ ДЛЯ ТОЧНОСТІ:
1.  **Цифри та Зірки (★) в Рангах:** Дуже уважно розпізнавай УСІ цифри в показниках **Найвищого Рангу Сезону** (наприклад, 'Міфічна Слава 267 ★', 'Міфічний 15 ★'). Не пропускай цифри.
2.  **Найвищий Ранг Сезону:** Це ранг, іконка якого розташована біля підпису "Highest Rank". Часто він має показник зірок (★) або очок слави. Вказуй повну назву рангу та кількість зірок/очок, якщо вони є.
3.  **Відсутність Даних:** Якщо будь-яка інформація (наприклад, локація, нікнейм, ID, найвищий ранг) дійсно відсутня на скріншоті або нерозбірлива, використовуй значення `null` для відповідного поля в JSON.
4.  **Точність ID та Сервера:** Уважно розпізнавай цифри ID та сервера. Якщо сервер не видно, вказуй тільки ID (наприклад, '123456789'). Якщо ID не видно, але видно сервер, вказуй `null`. Якщо нічого не видно, `null`.

Будь максимально точним. Якщо якась інформація відсутня на скріншоті, використовуй значення null для відповідного поля.
Розпізнавай текст уважно, навіть якщо він невеликий або частково перекритий.
"""

PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — крутий стрімер та аналітик Mobile Legends, який розмовляє з гравцями на їхній мові. Твоє завдання — дати короткий, емоційний та дружній коментар-враження про профіль гравця на 2-4 речення.
Не роби розгорнутий аналіз, лише емоційний та короткий коментар на 2-4 речення.

Ось дані з профілю:
- Нікнейм: {game_nickname}
- Найвищий ранг сезону: {highest_rank_season}
- Матчів зіграно: {matches_played}
- Лайків отримано: {likes_received}
- Локація: {location}
- Сквад: {squad_name}

Напиши 2-4 речення українською мовою, використовуючи ігровий сленг MLBB (наприклад, "тащер", "імба", "фармить як боженька", "в топі", "розносить катки").
Зроби акцент на якихось цікавих моментах профілю (багато матчів, високий ранг, багато лайків, цікавий нік, належність до скваду).
Головне — щоб було дружньо, з гумором (якщо доречно) і по-геймерськи.
Не треба перераховувати всі дані, просто дай загальне враження та позитивний коментар.
Відповідь – ТІЛЬКИ сам текст коментаря, без привітань типу "Привіт, {user_name}!".
Не використовуй Markdown або HTML теги у своїй відповіді. Тільки чистий текст.
"""

class MLBBChatGPT:
    """Клас для взаємодії з OpenAI API для генерації тексту та аналізу зображень."""
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=60),
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
        if exc_type:
            self.class_logger.error(f"Помилка в MLBBChatGPT: {exc_type} {exc_val}", exc_info=True)

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """Створює системний промпт для текстових запитів до GPT."""
        kyiv_tz = timezone(timedelta(hours=3))
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.3 🎮
## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, AI-експерт Mobile Legends Bang Bang. Твоя головна мета – надавати точну та перевірену інформацію.
ВАЖЛИВО: Не вигадуй імена героїв або механіки. Якщо ти не впевнений на 100% в імені героя або деталі, краще зазнач це або запропонуй перевірити.
## КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
- Платформа: Telegram (HTML, ВАЛІДНИЙ HTML ОБОВ'ЯЗКОВИЙ).
## СТАНДАРТИ ЯКОСТІ ВІДПОВІДЕЙ
### 🎯 СТРУКТУРА ТА ЗМІСТ:
1.  **Привітання**: "{greeting}, {user_name}! 👋"
2.  **Основна відповідь**:
    *   Чітка, конкретна інформація по суті запиту, базуючись на перевірених даних про гру.
    *   Якщо запит стосується вибору героїв: ОБОВ'ЯЗКОВО запропонуй 2-3 ІСНУЮЧИХ, АКТУАЛЬНИХ героїв Mobile Legends.
    *   Коротко поясни, чому ці реальні герої є хорошим вибором.
    *   Якщо доречно, згадай про можливі комбінації.
3.  **Практичні поради**: Декілька дієвих порад.
4.  **Мотивація**: Позитивне завершення.
### 📝 ФОРМАТУВАННЯ (ВАЛІДНИЙ HTML):
-   ТІЛЬКИ HTML: <b>жирний</b>, <i>курсив</i>, <code>код</code>. ЗАВЖДИ КОРЕКТНО ЗАКРИВАЙ ТЕГИ.
-   Списки: використовуй "• " для маркерів першого рівня, "  ◦ " для другого рівня.
-   Обсяг: ~200-300 слів.
-   Емодзі: доречно (🦸‍♂️, 💡, 🤝).
### 🎮 ЕКСПЕРТИЗА MLBB (ТІЛЬКИ ФАКТИЧНА ІНФОРМАЦІЯ):
-   **Герої**: ТІЛЬКИ ІСНУЮЧІ герої, їх механіки, ролі, контрпіки.
-   **Стратегії, Ранкінг, Психологія, Патч**: актуальна та перевірена інформація.
### ❌ КАТЕГОРИЧНО ЗАБОРОНЕНО:
-   ВИГАДУВАТИ імена героїв, здібності, предмети або будь-які інші ігрові сутності. Це найважливіше правило.
-   Надавати неперевірену або спекулятивну інформацію.
-   Markdown, НЕЗАКРИТІ HTML теги (ти повинен сам закривати теги).
## ПРИКЛАД СТИЛЮ (запит "контрпік проти Хаябуси"):
"{greeting}, {user_name}! 👋
Хаябуса може бути складним суперником, але є герої, які добре йому протистоять! 🤺
🦸‍♂️ <b>Кого можна взяти проти Хаябуси:</b>
• <b>Кайя (Kaja):</b> Його ультімейт <i>"Divine Judgment"</i> дозволяє схопити Хаябусу навіть під час його тіней та відтягнути до команди.
• <b>Хуфра (Khufra):</b> Його навички контролю, особливо <i>"Bouncing Ball"</i>, можуть зупинити Хаябусу та не дати йому втекти або використати тіні.
• <b>Сабер (Saber):</b> З правильним білдом, ультімейт Сабера <i>"Triple Sweep"</i> може швидко знищити Хаябусу до того, як він встигне завдати багато шкоди.
💡 <b>Порада:</b> Проти Хаябуси важливий хороший віжн на карті та швидка реакція команди на його появу.
Пам'ятай, що успіх залежить не тільки від героя, а й від твоїх навичок та командної гри! Успіхів! 👍"
## ЗАПИТ ВІД {user_name}: "{user_query}"
Твоя експертна відповідь (ПАМ'ЯТАЙ: БЕЗ ВИГАДОК, тільки фактичні герої та інформація, валідний HTML):"""

    def _beautify_response(self, text: str) -> str:
        """Форматує відповідь GPT, додаючи емодзі та HTML-теги, забезпечуючи валідність HTML."""
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

        # Обробка Markdown-подібних заголовків (##, ###)
        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        
        # Обробка Markdown-подібних списків
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+[\-\*]\s+", "  ◦ ", text, flags=re.MULTILINE) # Для вкладених списків

        # Нормалізація переносів рядків
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Видалено рядки, що конвертували Markdown **bold** та *italic* в HTML,
        # оскільки GPT вже має повертати HTML.
        # text = re.sub(r"\\*\\*(?P<content>.+?)\\*\\*", r"<b>\g<content></b>", text) # Видалено
        # text = re.sub(r"\\*(?P<content>.+?)\\*", r"<i>\g<content></i>", text) # Видалено

        # Балансування HTML тегів
        tags_to_balance = ["b", "i", "code"]
        for tag in tags_to_balance:
            open_tag = f"<{tag}>"
            close_tag = f"</{tag}>"
            open_count = len(re.findall(re.escape(open_tag), text))
            close_count = len(re.findall(re.escape(close_tag), text))

            if open_count > close_count:
                missing_tags = open_count - close_count
                self.class_logger.warning(f"Beautify: Виявлено {missing_tags} незакритих тегів {open_tag}. Додаю їх в кінець.")
                text += close_tag * missing_tags
            elif close_count > open_count:
                self.class_logger.warning(f"Beautify: Виявлено {close_count - open_count} зайвих тегів {close_tag}.")
                # Removing extra closing tags is more complex and risky, so we'll just log it.

        self.class_logger.debug(f"Beautify: Текст після обробки (перші 100 символів): '{text[:100]}'")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str: # Для /go
        """Отримує відповідь від GPT на текстовий запит користувача."""
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name}': '{user_query}'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4.1",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000,
            "temperature": 0.65,
            "top_p": 0.9,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2
        }
        self.class_logger.debug(f"Параметри тексту для GPT: temperature={payload['temperature']}")
        try:
            if not self.session or self.session.closed:
                 self.class_logger.warning("Aiohttp сесія для текстового GPT була закрита або відсутня. Перестворюю.")
                 self.session = ClientSession(
                    timeout=ClientTimeout(total=45),
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions", json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (текст): {response.status} - {error_text}")
                    return f"Вибач, {html.escape(user_name)}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status})."
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (текст): несподівана структура - {result}")
                    return f"Вибач, {html.escape(user_name)}, ШІ повернув несподівану відповідь 🤯."
                raw_gpt_text = result["choices"][0]["message"]["content"]
                self.class_logger.info(f"Сира відповідь від текстового GPT (перші 100): '{raw_gpt_text[:100]}'")
                return self._beautify_response(raw_gpt_text)
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (текст) для: '{user_query}'")
            return f"Вибач, {html.escape(user_name)}, запит до ШІ зайняв забагато часу ⏳."
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка текстового GPT для '{user_query}': {e}")
            return f"Не вдалося обробити твій запит, {html.escape(user_name)} 😕."

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        """Аналізує зображення за допомогою Vision API."""
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70]}...'")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            "max_tokens": 1500,
            "temperature": 0.3
        }
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")

        try:
            # Use a temporary session for Vision API calls to ensure it's fresh and has correct headers if main session is used elsewhere.
            async with ClientSession(headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session: # Changed to use self.api_key consistently
                async with temp_session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers, # Content-Type is also important here
                    json=payload,
                    timeout=ClientTimeout(total=90)
                ) as response:
                    return await self._handle_vision_response(response)
        except asyncio.TimeoutError:
            self.class_logger.error("Vision API Timeout помилка.")
            return {"error": "Запит до Vision API зайняв занадто багато часу."}
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка під час виклику Vision API: {e}")
            return {"error": f"Загальна помилка при аналізі зображення: {str(e)}"}


    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        """Обробляє відповідь від Vision API."""
        if response.status == 200:
            try:
                result = await response.json()
            except aiohttp.ContentTypeError:
                raw_text_response = await response.text()
                self.class_logger.error(f"Vision API відповідь не є JSON. Статус: {response.status}. Відповідь: {raw_text_response[:300]}")
                return {"error": "Vision API повернуло не JSON відповідь.", "raw_response": raw_text_response}

            content = result.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                self.class_logger.info(f"Vision API відповідь отримана (перші 100 символів): {content[:100]}")
                # Покращена логіка вилучення JSON, особливо якщо він не обрамлений ```json ... ```
                json_str = content.strip()
                if json_str.startswith("```json"):
                    json_str = json_str[len("```json"):].strip()
                if json_str.endswith("```"):
                    json_str = json_str[:-len("```")].strip()
                
                # Додаткове очищення для випадків, коли JSON не ідеально вирівняний
                if not json_str.startswith("{") and "{" in json_str:
                    json_str = json_str[json_str.find("{"):]
                if not json_str.endswith("}") and "}" in json_str:
                    json_str = json_str[:json_str.rfind("}")+1]

                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    self.class_logger.error(f"Помилка декодування JSON з Vision API: {e}. Рядок: '{json_str[:300]}'")
                    return {"error": "Не вдалося розпарсити JSON відповідь від Vision API.", "raw_response": content} # Повертаємо оригінальний content для діагностики
            else:
                self.class_logger.error(f"Vision API відповідь без контенту: {result}")
                return {"error": "Vision API повернуло порожню відповідь."}
        else:
            error_text = await response.text()
            self.class_logger.error(f"Vision API помилка: {response.status} - {error_text[:300]}")
            return {"error": f"Помилка Vision API: {response.status}", "details": error_text[:200]}

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        """Генерує дружній опис профілю на основі даних від Vision API."""
        self.class_logger.info(f"Запит на генерацію опису профілю для '{user_name}'.")

        escaped_profile_data = {k: html.escape(str(v)) if v is not None else "Не вказано" for k, v in profile_data.items()}

        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(
            user_name=html.escape(user_name),
            game_nickname=escaped_profile_data.get("game_nickname", "Не вказано"),
            highest_rank_season=escaped_profile_data.get("highest_rank_season", "Не вказано"),
            matches_played=escaped_profile_data.get("matches_played", "N/A"),
            likes_received=escaped_profile_data.get("likes_received", "N/A"),
            location=escaped_profile_data.get("location", "Не вказано"),
            squad_name=escaped_profile_data.get("squad_name", "Немає"),
        )
        payload = {
            "model": "gpt-4.1",
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 300,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        self.class_logger.debug(f"Параметри для опису профілю: temp={payload['temperature']}, max_tokens={payload['max_tokens']}")

        try:
            if not self.session or self.session.closed:
                 self.class_logger.warning("Aiohttp сесія для опису профілю була закрита або відсутня. Перестворюю.")
                 self.session = ClientSession(
                    timeout=ClientTimeout(total=30),
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions", json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): {response.status} - {error_text}")
                    return "<i>Не вдалося згенерувати дружній опис.</i>"
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): несподівана структура - {result}")
                    return "<i>Не вдалося отримати опис від ШІ.</i>"

                description_text = result["choices"][0]["message"]["content"].strip()
                self.class_logger.info(f"Згенеровано опис профілю: '{description_text[:100]}'")
                # Оскільки PROFILE_DESCRIPTION_PROMPT_TEMPLATE вимагає "Не використовуй Markdown або HTML теги",
                # ми не маємо ескейпити тут.
                return description_text
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис профілю) для: '{user_name}'")
            return "<i>Опис профілю генерувався занадто довго...</i>"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис профілю) для '{user_name}': {e}")
            return "<i>Виникла помилка при генерації опису.</i>"

bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обробник команди /start. Надсилає вітальне повідомлення з зображенням."""
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
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

👇 Для початку роботи, використай одну з команд:
• <code>/analyzeprofile</code> – для аналізу скріншота.
• <code>/go &lt;твоє питання&gt;</code> – для консультації (наприклад, <code>/go найкращий танк</code>).
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
"""
        try:
            await message.answer(fallback_text, parse_mode=ParseMode.HTML)
            logger.info(f"Резервне текстове привітання для {user_name_escaped} надіслано.")
        except TelegramAPIError as e_text:
            logger.error(f"Не вдалося надіслати навіть резервне текстове привітання для {user_name_escaped}: {e_text}")

@dp.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext):
    """Обробник команди /go. Надсилає запит до GPT та відповідь частинами, якщо потрібно."""
    await state.clear()
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""

    logger.info(f"Користувач {user_name_escaped} (ID: {user_id}) зробив запит з /go: '{user_query}'")

    if not user_query:
        logger.info(f"Порожній запит /go від {user_name_escaped}.")
        await message.reply(
            f"Привіт, <b>{user_name_escaped}</b>! 👋\n"
            "Напиши своє питання після <code>/go</code>, наприклад:\n"
            "<code>/go найкращі герої для міду</code>"
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
    response_text = f"Вибач, {user_name_escaped}, сталася непередбачена помилка при генерації відповіді. 😔" # Default error
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name_escaped, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}' від {user_name_escaped}: {e}")
        # response_text вже встановлено на повідомлення про помилку

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
            final_error_msg = f"Вибач, {user_name_escaped}, сталася критична помилка при відправці відповіді. Спробуйте пізніше. (Код: GO_SEND_FAIL)"
            if thinking_msg: # No need to check is_bot, as we created it. Check if it exists.
                 try:
                    await thinking_msg.edit_text(final_error_msg, parse_mode=None)
                 except TelegramAPIError: # If editing failed (e.g., message deleted by user or other issue)
                    await message.reply(final_error_msg, parse_mode=None)
            else: # thinking_msg was not sent or already handled
                await message.reply(final_error_msg, parse_mode=None)
        except Exception as final_err_send:
            logger.error(f"Зовсім не вдалося надіслати фінальне повідомлення про помилку для {user_name_escaped}: {final_err_send}")


@dp.message(Command("analyzeprofile"))
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

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
async def handle_profile_screenshot(message: Message, state: FSMContext):
    """Обробляє надісланий скріншот профілю."""
    bot_instance = message.bot
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    user_id = user.id if user else "невідомий"
    chat_id = message.chat.id
    logger.info(f"Отримано скріншот профілю від {user_name_escaped} (ID: {user_id}).")

    if not message.photo:
        await message.answer("Щось пішло не так. Будь ласка, надішли саме фото (скріншот).")
        return

    photo_file_id = message.photo[-1].file_id

    try:
        await message.delete()
        logger.info(f"Повідомлення користувача {user_name_escaped} зі скріншотом видалено.")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача {user_name_escaped} зі скріншотом: {e}")

    await state.update_data(vision_photo_file_id=photo_file_id, original_user_name=user_name_escaped)

    caption_text = "Скріншот профілю отримано.\nНатисніть «🔍 Аналіз», щоб дізнатися більше."

    analyze_button = InlineKeyboardButton(text="🔍 Аналіз", callback_data="trigger_vision_analysis")
    delete_preview_button = InlineKeyboardButton(text="🗑️ Видалити", callback_data="delete_bot_message")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[analyze_button, delete_preview_button]])

    try:
        sent_message = await bot_instance.send_photo(
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
            await bot_instance.send_message(chat_id, "Не вдалося обробити ваш запит на аналіз. Спробуйте ще раз.")
        except TelegramAPIError as send_err:
            logger.error(f"Не вдалося надіслати повідомлення про помилку обробки аналізу для {user_name_escaped}: {send_err}")
        await state.clear()


@dp.callback_query(F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext):
    """Обробляє натискання кнопки "Аналіз", викликає Vision API та надсилає результат."""
    bot_instance = callback_query.bot
    if not callback_query.message or not callback_query.message.chat:
        logger.error("trigger_vision_analysis_callback: callback_query.message або callback_query.message.chat is None.")
        await callback_query.answer("Помилка: не вдалося обробити запит.", show_alert=True)
        await state.clear()
        return

    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id # This is the bot's message with the photo and button

    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")

    try:
        # Edit caption to show processing, remove buttons
        if callback_query.message.caption:
            await callback_query.message.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {user_name}...",
                reply_markup=None
            )
        else: # Should not happen if we sent it with caption, but as a fallback
             await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...") # Acknowledge button press
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name}: {e}")

    photo_file_id = user_data.get("vision_photo_file_id")

    if not photo_file_id:
        logger.error(f"File_id не знайдено в стані для аналізу для {user_name}.")
        try:
            if callback_query.message.caption: # Check if message still exists and has caption
                await callback_query.message.edit_caption(caption=f"Помилка, {user_name}: дані для аналізу втрачено. Спробуйте надіслати скріншот знову (/analyzeprofile).", reply_markup=None)
        except TelegramAPIError: pass # Ignore if editing fails
        await state.clear()
        return

    final_caption_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"

    try:
        file_info = await bot_instance.get_file(photo_file_id)
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")

        downloaded_file_io = await bot_instance.download_file(file_info.file_path)
        if downloaded_file_io is None: # download_file can return None
            raise ValueError("Не вдалося завантажити файл з Telegram для аналізу (download_file повернув None).")

        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
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
                    if value is not None: # Check for None, empty string or 0 are valid.
                        display_value = str(value)
                        # Specific formatting for rank
                        if key == "highest_rank_season" and ("★" in display_value or "зірок" in display_value.lower() or "слава" in display_value.lower()):
                            if "★" not in display_value: # Normalize to star symbol
                                 display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                            display_value = re.sub(r'\s+★', '★', display_value) # Remove space before star
                        response_parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
                        has_data = True
                    else:
                         response_parts.append(f"<b>{readable_name}:</b> <i>не розпізнано</i>")

                if not has_data and analysis_result_json.get("raw_response"): # Check if raw_response exists
                     response_parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>\nДеталі з Vision: {html.escape(str(analysis_result_json.get('raw_response'))[:150])}...")
                elif not has_data:
                     response_parts.append(f"\n<i>Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")

                structured_data_text = "\n".join(response_parts)
                # Get plain text description
                profile_description_plain = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                # Since description is plain text, we escape it for HTML context if needed, or send as is if it's meant to be plain.
                # Given PROFILE_DESCRIPTION_PROMPT_TEMPLATE says "Не використовуй Markdown або HTML", we assume it's plain.
                # It will be part of an HTML message, so special HTML chars in it should be escaped.
                final_caption_text = f"{structured_data_text}\n\n{html.escape(profile_description_plain)}"


            else:
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана або порожня.'
                logger.error(f"Помилка аналізу профілю (JSON) для {user_name}: {error_msg}")
                final_caption_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"
                if analysis_result_json and analysis_result_json.get("raw_response"):
                    final_caption_text += f"\nДеталі: {html.escape(str(analysis_result_json.get('raw_response'))[:100])}..."
                elif analysis_result_json and analysis_result_json.get("details"):
                     final_caption_text += f"\nДеталі: {html.escape(str(analysis_result_json.get('details'))[:100])}..."

    except TelegramAPIError as e:
        logger.exception(f"Telegram API помилка під час обробки файлу для {user_name}: {e}")
        final_caption_text = f"Пробач, {user_name}, виникла проблема з доступом до файлу скріншота в Telegram."
    except ValueError as e: # Catch specific ValueError from our code
        logger.exception(f"Помилка значення під час обробки файлу для {user_name}: {e}")
        final_caption_text = f"На жаль, {user_name}, не вдалося коректно обробити файл скріншота."
    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота профілю для {user_name}: {e}")
        # final_caption_text is already set to a default error message
        final_caption_text = f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."


    try:
        if callback_query.message: # Ensure message object exists
            if len(final_caption_text) > 1024: # Telegram caption limit for media
                logger.warning(f"Підпис до фото для {user_name} задовгий ({len(final_caption_text)} символів). Редагую фото без підпису і надсилаю текст окремо.")
                # Remove buttons from photo if caption is too long and will be sent separately
                await bot_instance.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
                # Send the long text using send_message_in_chunks
                await send_message_in_chunks(bot_instance, chat_id, final_caption_text, ParseMode.HTML)
            else:
                await bot_instance.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=final_caption_text,
                    reply_markup=None, # Кнопки видаляються
                    parse_mode=ParseMode.HTML
                )
            logger.info(f"Результати аналізу для {user_name} відредаговано/надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати/надіслати повідомлення з результатами аналізу для {user_name}: {e}. Спроба надіслати як нове повідомлення.")
        try:
            # Fallback to sending as a new message(s) if editing caption failed
            await send_message_in_chunks(bot_instance, chat_id, final_caption_text, ParseMode.HTML)
        except Exception as send_err:
            logger.error(f"Не вдалося надіслати нове повідомлення з аналізом для {user_name}: {send_err}")
            if callback_query.message: # Check again, as it might be None now
                try:
                    await bot_instance.send_message(chat_id, f"Вибачте, {user_name}, сталася помилка при відображенні результатів аналізу. Спробуйте пізніше.")
                except Exception as final_fallback_err:
                     logger.error(f"Не вдалося надіслати навіть текстове повідомлення про помилку аналізу для {user_name}: {final_fallback_err}")

    await state.clear()

@dp.callback_query(F.data == "delete_bot_message")
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
        # Only clear state if it was specifically for this analysis flow
        if current_state_str == VisionAnalysisStates.awaiting_analysis_trigger.state:
            user_name = (await state.get_data()).get("original_user_name", "Користувач")
            logger.info(f"Прев'ю аналізу видалено користувачем {user_name}, стан очищено.")
            await state.clear()
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота (ймовірно, прев'ю): {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)


@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, Command("cancel"))
@dp.message(VisionAnalysisStates.awaiting_analysis_trigger, Command("cancel"))
async def cancel_profile_analysis(message: Message, state: FSMContext):
    """Обробник команди /cancel під час аналізу профілю."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    logger.info(f"Користувач {user_name_escaped} скасував аналіз профілю командою /cancel.")

    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id and message.chat: # Ensure message.chat exists
        try:
            # It's the bot's own message, so use message.bot or bot instance
            await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            logger.info(f"Видалено повідомлення-прев'ю бота (ID: {bot_message_id}) після скасування аналізу {user_name_escaped}.")
        except TelegramAPIError: # Bot may not have permission or message already deleted
            logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота (ID: {bot_message_id}) при скасуванні для {user_name_escaped}.")

    await state.clear()
    await message.reply(f"Аналіз скріншота скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go.")

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot)
@dp.message(VisionAnalysisStates.awaiting_analysis_trigger)
async def handle_wrong_input_for_profile_screenshot(message: Message, state: FSMContext):
    """Обробляє некоректне введення під час очікування скріншота або тригера аналізу."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")

    # Check for /cancel command text explicitly
    if message.text and message.text.lower() == "/cancel":
        await cancel_profile_analysis(message, state)
        return

    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data()
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try: await bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError: pass
        await state.clear()
        await cmd_go(message, state) # Pass the current message to cmd_go
        return # Important to return after handling

    # If not /cancel or /go, then it's unexpected input for the current state
    current_state_name = await state.get_state()
    if current_state_name == VisionAnalysisStates.awaiting_profile_screenshot.state:
        logger.info(f"Користувач {user_name_escaped} надіслав не фото у стані awaiting_profile_screenshot. Пропоную скасувати або надіслати фото.")
        await message.reply(f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) свого профілю або команду /cancel для скасування.")
    elif current_state_name == VisionAnalysisStates.awaiting_analysis_trigger.state:
        logger.info(f"Користувач {user_name_escaped} надіслав '{html.escape(message.text or 'не текстове повідомлення')}' у стані awaiting_analysis_trigger. Пропоную скасувати або використати кнопки.")
        await message.reply(f"Очікувалася дія з аналізом (кнопка під фото) або команда /cancel, {user_name_escaped}.")
    else: # Should not happen if states are handled, but as a fallback
        logger.info(f"Користувач {user_name_escaped} надіслав некоректне введення у стані аналізу. Пропоную скасувати.")
        await message.reply(f"Щось пішло не так. Використай /cancel для скасування поточного аналізу, {user_name_escaped}.")


@dp.errors()
async def error_handler(update_event, exception: Exception):
    """Глобальний обробник помилок."""
    logger.error(f"Глобальна помилка в error_handler: {exception} для update: {update_event}", exc_info=True)

    chat_id: Optional[int] = None
    user_name: str = "друже" # Default user name

    # Try to extract chat_id and user_name from the update_event
    if hasattr(update_event, 'message') and update_event.message:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = html.escape(update_event.message.from_user.first_name or "Гравець")
    elif hasattr(update_event, 'callback_query') and update_event.callback_query:
        if update_event.callback_query.message and update_event.callback_query.message.chat :
             chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = html.escape(update_event.callback_query.from_user.first_name or "Гравець")
        try:
            # Acknowledge callback query to prevent "loading" state on client
            await update_event.callback_query.answer("Сталася помилка...", show_alert=False)
        except Exception: pass # Ignore if answer fails

    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилинку або використай іншу команду."

    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None) # Send error as plain text
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді користувачу.")

async def main() -> None:
    """Головна функція запуску бота."""
    # Версія оновлена для логування
    bot_version = "v2.9.1 (покращена обробка HTML та помилок)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")
    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID != 0:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                admin_message = (
                    f"🤖 <b>MLBB IUI mini {bot_version} запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Промпт v2.3 (текст), Vision (профіль /analyzeprofile, 'вау-ефект' + опис ШІ) активні!</b>\n"
                    f"🔩 Моделі: Vision: <code>gpt-4o-mini</code>, Текст/Опис: <code>gpt-4.1</code> (жорстко задані)\n"
                    f"📄 Покращено обробку HTML та розбиття довгих повідомлень.\n"
                    f"🟢 Готовий до роботи!"
                )
                await bot.send_message(ADMIN_USER_ID, admin_message, parse_mode=ParseMode.HTML) # Ensure parse_mode for admin message
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
        logger.info("🛑 Зупинка бота та закриття сесій...")
        # Correctly close bot's session if it was implicitly created by aiogram or explicitly
        # The bot.session is an AiohttpSession object which has a close method.
        if bot.session and hasattr(bot.session, "close") and not bot.session.closed:
            try:
                await bot.session.close()
                logger.info("Сесію HTTP клієнта Bot закрито.")
            except Exception as e:
                logger.error(f"Помилка під час закриття сесії HTTP клієнта Bot: {e}", exc_info=True)

        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    asyncio.run(main())
