"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано функціонал аналізу скріншотів профілю гравця з "вау-ефектом" та описом від ШІ.

Python 3.11+ | aiogram 3.19+ | OpenAI
Author: MLBB-BOSS | Date: 2025-05-29 | Version: 3.0 (Fixed)
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

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

# Конфігурація
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
WELCOME_IMAGE_URL: str = "https://res.cloudinary.com/ha1pzppgf/image/upload/v1748286434/file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"

# Константи
MAX_TELEGRAM_MESSAGE_LENGTH: int = 4090
MAX_TELEGRAM_CAPTION_LENGTH: int = 1020
VISION_MODEL: str = "gpt-4o-mini"
TEXT_MODEL: str = "gpt-4"  # Виправлено з неіснуючого "gpt-4.1"

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

logger.info(f"Модель для Vision (аналіз скріншотів): {VISION_MODEL}")
logger.info(f"Модель для текстових генерацій (/go, опис профілю): {TEXT_MODEL}")

# === ДОПОМІЖНІ ФУНКЦІЇ ===

def validate_html_tags(text: str) -> str:
    """
    Валідує та виправляє HTML теги в тексті.
    
    Args:
        text: Текст з потенційно некоректними HTML тегами
        
    Returns:
        Текст з валідними HTML тегами
    """
    # Видаляємо всі некоректні теги та залишаємо тільки дозволені
    allowed_tags = ['b', 'i', 'code', 'pre', 'u', 's', 'spoiler']
    
    # Спочатку видаляємо всі HTML теги
    clean_text = re.sub(r'<[^>]+>', '', text)
    
    # Тепер додаємо коректні теги назад використовуючи markdown-подібний синтаксис
    # **жирний** -> <b>жирний</b>
    clean_text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', clean_text)
    # *курсив* -> <i>курсив</i>
    clean_text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', clean_text)
    # `код` -> <code>код</code>
    clean_text = re.sub(r'`([^`]+)`', r'<code>\1</code>', clean_text)
    
    return clean_text

def split_text_smart(text: str, max_length: int) -> List[str]:
    """
    Розумно розбиває текст на частини, зберігаючи HTML теги.
    
    Args:
        text: Текст для розбиття
        max_length: Максимальна довжина однієї частини
        
    Returns:
        Список частин тексту
    """
    if len(text) <= max_length:
        return [text]
    
    chunks: List[str] = []
    current_pos = 0
    
    while current_pos < len(text):
        # Знаходимо кращу точку розбиття
        end_pos = current_pos + max_length
        
        if end_pos >= len(text):
            chunks.append(text[current_pos:])
            break
        
        # Шукаємо найближчий перенос рядка або пробіл
        split_pos = text.rfind('\n', current_pos, end_pos)
        if split_pos == -1:
            split_pos = text.rfind(' ', current_pos, end_pos)
        if split_pos == -1:
            split_pos = end_pos
        
        chunk = text[current_pos:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        
        current_pos = split_pos + 1
    
    return chunks

async def send_long_message(
    bot_instance: Bot,
    chat_id: int,
    text: str,
    parse_mode: Optional[str] = ParseMode.HTML,
    initial_message: Optional[Message] = None
) -> bool:
    """
    Надсилає довге повідомлення, розбиваючи його на частини при необхідності.
    
    Args:
        bot_instance: Екземпляр бота
        chat_id: ID чату
        text: Текст для надсилання
        parse_mode: Режим парсингу (HTML/Markdown/None)
        initial_message: Початкове повідомлення для редагування
        
    Returns:
        True якщо успішно, False якщо помилка
    """
    if not text.strip():
        if initial_message:
            try:
                await initial_message.delete()
            except TelegramAPIError:
                pass
        return True
    
    # Валідуємо HTML
    if parse_mode == ParseMode.HTML:
        text = validate_html_tags(text)
    
    # Розбиваємо текст на частини
    chunks = split_text_smart(text, MAX_TELEGRAM_MESSAGE_LENGTH)
    
    success = True
    
    for i, chunk in enumerate(chunks):
        try:
            if i == 0 and initial_message:
                # Редагуємо перше повідомлення
                await initial_message.edit_text(chunk, parse_mode=parse_mode)
            else:
                # Надсилаємо нові повідомлення
                await bot_instance.send_message(chat_id, chunk, parse_mode=parse_mode)
                
            logger.info(f"Надіслано частину {i+1}/{len(chunks)} для chat_id {chat_id}")
            
        except TelegramAPIError as e:
            logger.error(f"Помилка надсилання частини {i+1} для chat_id {chat_id}: {e}")
            
            if "can't parse entities" in str(e).lower():
                # Спробуємо без парсингу
                try:
                    plain_chunk = re.sub(r'<[^>]+>', '', chunk)
                    if i == 0 and initial_message:
                        await initial_message.edit_text(plain_chunk, parse_mode=None)
                    else:
                        await bot_instance.send_message(chat_id, plain_chunk, parse_mode=None)
                    logger.info(f"Надіслано частину {i+1} як простий текст")
                except TelegramAPIError:
                    success = False
                    break
            else:
                success = False
                break
    
    return success

# === СТАНИ FSM ===
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
  "location": "string (наприклад, 'Ukraine/Dnipropetrovsk') або null",
  "squad_name": "string (наприклад, 'IS Iron Spirit.') або null"
}

КРИТИЧНО ВАЖЛИВІ ІНСТРУКЦІЇ ДЛЯ ТОЧНОСТІ:
1. **Цифри та Зірки (★) в Рангах:** Дуже уважно розпізнавай УСІ цифри в показниках **Найвищого Рангу Сезону**.
2. **Найвищий Ранг Сезону:** Це ранг, іконка якого розташована біля підпису "Highest Rank".
3. **Відсутність Даних:** Якщо будь-яка інформація дійсно відсутня на скріншоті, використовуй null.
4. **Точність ID та Сервера:** Уважно розпізнавай цифри ID та сервера.

Будь максимально точним. Розпізнавай текст уважно, навіть якщо він невеликий або частково перекритий.
"""

PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — крутий стрімер та аналітик Mobile Legends, який розмовляє з гравцями на їхній мові. 
Твоє завдання — дати короткий, емоційний та дружній коментар про профіль гравця.
Не роби розгорнутий аналіз, лише емоційний та короткий коментар на 2-4 речення.

Ось дані з профілю:
- Нікнейм: {game_nickname}
- Найвищий ранг сезону: {highest_rank_season}
- Матчів зіграно: {matches_played}
- Лайків отримано: {likes_received}
- Локація: {location}
- Сквад: {squad_name}

Напиши 2-4 речення українською мовою, використовуючи ігровий сленг MLBB (наприклад, "тащер", "імба", "фармить").
Зроби акцент на якихось цікавих моментах профілю (багато матчів, високий ранг, багато лайків, цікавий нік).
Головне — щоб було дружньо, з гумором (якщо доречно) і по-геймерськи.
Не треба перераховувати всі дані, просто дай загальне враження та позитивний коментар.
Відповідь – ТІЛЬКИ сам текст коментаря, без привітань.
Не використовуй HTML або Markdown теги у своїй відповіді.
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
            
        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v3.0 🎮

## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, AI-експерт Mobile Legends Bang Bang. Твоя головна мета – надавати точну та перевірену інформацію.
ВАЖЛИВО: Не вигадуй імена героїв або механіки. Якщо ти не впевнений на 100% в імені героя або деталі, краще зазнач це.

## КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
- Платформа: Telegram (HTML форматування)

## СТАНДАРТИ ЯКОСТІ ВІДПОВІДЕЙ
### 🎯 СТРУКТУРА ТА ЗМІСТ:
1. **Привітання**: "{greeting}, {user_name}! 👋"
2. **Основна відповідь**:
   * Чітка, конкретна інформація по суті запиту
   * Якщо запит стосується вибору героїв: ОБОВ'ЯЗКОВО запропонуй 2-3 ІСНУЮЧИХ героїв Mobile Legends
   * Коротко поясни, чому ці герої є хорошим вибором
   * Якщо доречно, згадай про можливі комбінації
3. **Практичні поради**: Декілька дієвих порад
4. **Мотивація**: Позитивне завершення

### 📝 ФОРМАТУВАННЯ (ВАЛІДНИЙ HTML):
- ТІЛЬКИ HTML: **жирний**, *курсив*, `код`. ЗАВЖДИ КОРЕКТНО ЗАКРИВАЙ ТЕГИ.
- Списки: "• "
- Обсяг: ~200-300 слів
- Емодзі: доречно (🦸‍♂️, 💡, 🤝)

### 🎮 ЕКСПЕРТИЗА MLBB (ТІЛЬКИ ФАКТИЧНА ІНФОРМАЦІЯ):
- **Герої**: ТІЛЬКИ ІСНУЮЧІ герої, їх механіки, ролі, контрпіки
- **Стратегії, Ранкінг, Психологія, Патч**: актуальна та перевірена інформація

### ❌ КАТЕГОРИЧНО ЗАБОРОНЕНО:
- ВИГАДУВАТИ імена героїв, здібності, предмети або будь-які інші ігрові сутності
- Надавати неперевірену або спекулятивну інформацію
- Markdown, НЕЗАКРИТІ HTML теги

## ЗАПИТ ВІД {user_name}: "{user_query}"
Твоя експертна відповідь (ПАМ'ЯТАЙ: БЕЗ ВИГАДОК, тільки фактичні герої та інформація, валідний HTML):"""

    async def get_response(self, user_name: str, user_query: str) -> str:
        """Отримує відповідь від GPT на текстовий запит користувача."""
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name}': '{user_query}'")
        
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": TEXT_MODEL,
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
        
        try:
            if not self.session or self.session.closed:
                self.class_logger.warning("Aiohttp сесія для текстового GPT була закрита. Перестворюю.")
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
                    self.class_logger.error(f"OpenAI API помилка (текст): {response.status} - {error_text}")
                    return f"Вибач, {html.escape(user_name)}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status})."
                
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message"):
                    self.class_logger.error(f"OpenAI API помилка (текст): несподівана структура - {result}")
                    return f"Вибач, {html.escape(user_name)}, ШІ повернув несподівану відповідь 🤯."
                
                raw_gpt_text = result["choices"][0]["message"]["content"]
                self.class_logger.info(f"Сира відповідь від текстового GPT (перші 100): '{raw_gpt_text[:100]}'")
                
                # Простіше форматування без складних regex
                formatted_text = self._simple_format_response(raw_gpt_text)
                return formatted_text
                
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (текст) для: '{user_query}'")
            return f"Вибач, {html.escape(user_name)}, запит до ШІ зайняв забагато часу ⏳."
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка текстового GPT для '{user_query}': {e}")
            return f"Не вдалося обробити твій запит, {html.escape(user_name)} 😕."

    def _simple_format_response(self, text: str) -> str:
        """Просте форматування відповіді без складних regex операцій."""
        # Видаляємо зайві пробіли та переноси
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        # Проста заміна markdown на HTML
        text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*([^*\n]+)\*', r'<i>\1</i>', text)
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        
        # Заміна символів списку
        text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)
        
        return text

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        """Аналізує зображення за допомогою Vision API."""
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70]}...'")
        
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": VISION_MODEL,
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

        try:
            async with ClientSession(headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session:
                async with temp_session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
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
                
                # Пошук JSON у відповіді
                json_match = re.search(r'```json\s*([\s\S]+?)\s*```', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content.strip()

                try:
                    # Очищення JSON рядка
                    if not json_str.startswith("{") and "{" in json_str:
                        json_str = json_str[json_str.find("{"):]
                    if not json_str.endswith("}") and "}" in json_str:
                        json_str = json_str[:json_str.rfind("}")+1]

                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    self.class_logger.error(f"Помилка декодування JSON з Vision API: {e}. Рядок: '{json_str[:300]}'")
                    return {"error": "Не вдалося розпарсити JSON відповідь від Vision API.", "raw_response": content}
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

        escaped_profile_data = {
            k: html.escape(str(v)) if v is not None else "Не вказано" 
            for k, v in profile_data.items()
        }

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
            "model": TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 300,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }

        try:
            if not self.session or self.session.closed:
                self.class_logger.warning("Aiohttp сесія для опису профілю була закрита. Перестворюю.")
                self.session = ClientSession(
                    timeout=ClientTimeout(total=30),
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
            
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions", 
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): {response.status} - {error_text}")
                    return "Не вдалося згенерувати дружній опис."
                
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message"):
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): несподівана структура - {result}")
                    return "Не вдалося отримати опис від ШІ."

                description_text = result["choices"][0]["message"]["content"].strip()
                self.class_logger.info(f"Згенеровано опис профілю: '{description_text[:100]}'")
                return description_text
                
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис профілю) для: '{user_name}'")
            return "Опис профілю генерувався занадто довго..."
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис профілю) для '{user_name}': {e}")
            return "Виникла помилка при генерації опису."

# === ІНІЦІАЛІЗАЦІЯ БОТА ===
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# === ОБРОБНИКИ ===
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

Ласкаво просимо до <b>MLBB IUI mini v3.0</b>! 🎮
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
Ласкаво просимо до <b>MLBB IUI mini v3.0</b>! 🎮
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
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v3.0 GPT ({TEXT_MODEL})</i>"

    full_response_to_send = f"{response_text}{admin_info}"

    # Використовуємо нову функцію для надсилання довгих повідомлень
    success = await send_long_message(
        bot_instance=bot,
        chat_id=message.chat.id,
        text=full_response_to_send,
        parse_mode=ParseMode.HTML,
        initial_message=thinking_msg
    )

    if success:
        logger.info(f"Відповідь /go для {user_name_escaped} успішно надіслано.")
    else:
        logger.error(f"Не вдалося надіслати відповідь /go для {user_name_escaped}")
        try:
            await message.reply(f"Вибач, {user_name_escaped}, сталася помилка при відправці відповіді.")
        except TelegramAPIError:
            pass

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
    message_id = callback_query.message.message_id

    user_data = await state.get_data()
    user_name = user_data.get("original_user_name", "Гравець")

    try:
        if callback_query.message.caption:
            await callback_query.message.edit_caption(
                caption=f"⏳ Обробляю ваш скріншот, {user_name}...",
                reply_markup=None
            )
        else:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом для {user_name}: {e}")

    photo_file_id = user_data.get("vision_photo_file_id")

    if not photo_file_id:
        logger.error(f"File_id не знайдено в стані для аналізу для {user_name}.")
        try:
            if callback_query.message.caption:
                await callback_query.message.edit_caption(
                    caption=f"Помилка, {user_name}: дані для аналізу втрачено. Спробуйте надіслати скріншот знову."
                )
        except TelegramAPIError:
            pass
        await state.clear()
        return

    final_caption_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"

    try:
        file_info = await bot_instance.get_file(photo_file_id)
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу.")

        downloaded_file_io = await bot_instance.download_file(file_info.file_path)
        if downloaded_file_io is None:
            raise ValueError("Не вдалося завантажити файл з Telegram для аналізу.")

        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, PROFILE_SCREENSHOT_PROMPT)

            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз профілю (JSON) для {user_name}: {analysis_result_json}")
                
                response_parts = [f"<b>Детальний аналіз твого профілю, {user_name}:</b>"]
                fields_translation = {
                    "game_nickname": "🎮 Нікнейм",
                    "mlbb_id_server": "🆔 ID (Сервер)",
                    "highest_rank_season": "🌟 Найвищий ранг (сезон)",
                    "matches_played": "⚔️ Матчів зіграно",
                    "likes_received": "👍 Лайків отримано",
                    "location": "🌍 Локація",
                    "squad_name": "🛡️ Сквад"
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

                if not has_data:
                    response_parts.append(f"\n<i>Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")

                structured_data_text = "\n".join(response_parts)
                profile_description = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)

                final_caption_text = f"{structured_data_text}\n\n{profile_description}"

            else:
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу профілю (JSON) для {user_name}: {error_msg}")
                final_caption_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"

    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота профілю для {user_name}: {e}")
        final_caption_text = f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."

    # Використовуємо нову функцію для надсилання результатів
    try:
        if len(final_caption_text) > MAX_TELEGRAM_CAPTION_LENGTH:
            logger.warning(f"Підпис до фото для {user_name} задовгий ({len(final_caption_text)} символів). Надсилаю окремим повідомленням.")
            await bot_instance.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            await send_long_message(bot_instance, chat_id, final_caption_text, ParseMode.HTML)
        else:
            await bot_instance.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=final_caption_text,
                reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        logger.info(f"Результати аналізу для {user_name} відредаговано/надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати/надіслати повідомлення з результатами аналізу для {user_name}: {e}")
        await send_long_message(bot_instance, chat_id, final_caption_text, ParseMode.HTML)

    await state.clear()

@dp.callback_query(F.data == "delete_bot_message")
async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext):
    """Обробляє натискання кнопки "Видалити" на повідомленні-прев'ю скріншота."""
    if not callback_query.message:
        logger.error("delete_bot_message_callback: callback_query.message is None.")
        await callback_query.answer("Помилка видалення.", show_alert=True)
        return
    try:
        await callback_query.message.delete()
        await callback_query.answer("Повідомлення видалено.")
        current_state_str = await state.get_state()
        if current_state_str == VisionAnalysisStates.awaiting_analysis_trigger.state:
            user_name = (await state.get_data()).get("original_user_name", "Користувач")
            logger.info(f"Прев'ю аналізу видалено користувачем {user_name}, стан очищено.")
            await state.clear()
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота: {e}")
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
    if bot_message_id and message.chat:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            logger.info(f"Видалено повідомлення-прев'ю бота (ID: {bot_message_id}) після скасування аналізу {user_name_escaped}.")
        except TelegramAPIError:
            logger.warning(f"Не вдалося видалити повідомлення-прев'ю бота при скасуванні для {user_name_escaped}.")

    await state.clear()
    await message.reply(f"Аналіз скріншота скасовано, {user_name_escaped}. Ти можеш продовжити використовувати команду /go.")

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot)
@dp.message(VisionAnalysisStates.awaiting_analysis_trigger)
async def handle_wrong_input_for_profile_screenshot(message: Message, state: FSMContext):
    """Обробляє некоректне введення під час очікування скріншота або тригера аналізу."""
    user = message.from_user
    user_name_escaped = html.escape(user.first_name if user else "Гравець")
    
    if message.text and message.text.lower() == "/cancel":
        await cancel_profile_analysis(message, state)
        return

    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {user_name_escaped} ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data()
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id and message.chat:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError:
                pass
        await state.clear()
        await cmd_go(message, state)
    elif message.text:
        logger.info(f"Користувач {user_name_escaped} надіслав текст у стані аналізу. Пропоную скасувати.")
        await message.reply(f"Очікувався скріншот або дія з аналізом, {user_name_escaped}. Використай /cancel для скасування поточного процесу.")
    else:
        logger.info(f"Користувач {user_name_escaped} надіслав не фото і не текст у стані аналізу. Пропоную скасувати.")
        await message.reply(f"Будь ласка, {user_name_escaped}, надішли фото (скріншот) свого профілю або команду /cancel для скасування.")

@dp.errors()
async def error_handler(update_event, exception: Exception):
    """Глобальний обробник помилок."""
    logger.error(f"Глобальна помилка в error_handler: {exception} для update: {update_event}", exc_info=True)

    chat_id: Optional[int] = None
    user_name: str = "друже"

    if hasattr(update_event, 'message') and update_event.message:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = html.escape(update_event.message.from_user.first_name or "Гравець")
    elif hasattr(update_event, 'callback_query') and update_event.callback_query:
        if update_event.callback_query.message and update_event.callback_query.message.chat:
            chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = html.escape(update_event.callback_query.from_user.first_name or "Гравець")
        try:
            await update_event.callback_query.answer("Сталася помилка...", show_alert=False)
        except Exception:
            pass

    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину."

    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення про системну помилку в чат {chat_id}: {e}")
    else:
        logger.warning("Системна помилка, але не вдалося визначити chat_id для відповіді користувачу.")

async def main() -> None:
    """Головна функція запуску бота."""
    logger.info(f"🚀 Запуск MLBB IUI mini v3.0 (FIXED) ... (PID: {os.getpid()})")
    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        
        if ADMIN_USER_ID != 0:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                admin_message = (
                    f"🤖 <b>MLBB IUI mini v3.0 (FIXED) запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Виправлено HTML форматування!</b>\n"
                    f"🔩 Моделі: Vision: <code>{VISION_MODEL}</code>, Текст: <code>{TEXT_MODEL}</code>\n"
                    f"📄 Покращено розбиття довгих повідомлень.\n"
                    f"🟢 Готовий до роботи!"
                )
                await bot.send_message(ADMIN_USER_ID, admin_message)
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}")

        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt).")
    except TelegramAPIError as e:
        logger.critical(f"Критична помилка