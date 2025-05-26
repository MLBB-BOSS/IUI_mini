"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано функціонал аналізу скріншотів профілю гравця з "вау-ефектом" та описом від ШІ.
Моделі GPT жорстко встановлені в коді для аналізу та опису.

Python 3.11+ | aiogram 3.19+ | OpenAI
Author: MLBB-BOSS | Date: 2025-05-26
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

# Ці змінні завантажуються, але для ключових функцій моделі будуть жорстко задані нижче
# VISION_MODEL_NAME_FROM_ENV: str = os.getenv("VISION_MODEL_NAME", "gpt-4o")
# TEXT_MODEL_NAME_FROM_ENV: str = os.getenv("TEXT_MODEL_NAME", "gpt-4-turbo")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

logger.info(f"Модель для Vision (аналіз скріншотів): gpt-4o-mini (жорстко задано)")
logger.info(f"Модель для текстових генерацій (/go, опис профілю): gpt-4.1 (жорстко задано)")

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
  "current_rank": "string (наприклад, 'Епічний V', 'Легенда III', 'Міфічний 10 ★') або null",
  "highest_rank_season": "string (наприклад, 'Міфічна Слава 267 ★', 'Міфічна Слава 1111 ★') або null",
  "matches_played": "int або null",
  "likes_received": "int або null",
  "location": "string (наприклад, 'Ukraine/Dnipropetrovs'k') або null",
  "squad_name": "string (наприклад, 'IS Iron Spirit.') або null"
}

КРИТИЧНО ВАЖЛИВІ ІНСТРУКЦІЇ ДЛЯ ТОЧНОСТІ:
1.  **Цифри та Зірки (★):** Дуже уважно розпізнавай УСІ цифри в показниках рангу (наприклад, '1111' ★, а не '111' ★). Переконайся, що кількість цифр відповідає зображенню. Якщо є символ зірки (★) поруч з числом, включи його у значення поля "highest_rank_season" та "current_rank" після числа (наприклад, "Міфічна Слава 267 ★").
2.  **Поточний Ранг:** Це ранг, іконка якого зазвичай найбільша і розташована під блоком ID/Сервер, з підписом "Current Rank". Не плутай його з "Highest Rank" або "Mythical Glory Medal". Наприклад, якщо там іконка Епіка V, то так і пиши "Епічний V". Якщо є зірки, додай їх (наприклад, "Міфічний 10 ★").
3.  **Найвищий Ранг Сезону:** Це ранг, іконка якого розташована біля підпису "Highest Rank". Часто він має показник зірок поруч (наприклад, ★267 або ★1111). Записуй його як "Назва Рангу КІЛЬКІСТЬ ★".
4.  **Відсутність Даних:** Якщо інформація (наприклад, локація) дійсно відсутня на скріншоті, використовуй null.

Будь максимально точним. Якщо якась інформація відсутня на скріншоті, використовуй значення null для відповідного поля.
Розпізнавай текст уважно, навіть якщо він невеликий або частково перекритий.
Для рангів, якщо бачиш римські цифри ТА зірки, вказуй їх разом (наприклад, "Міфічний III 15 ★", "Легенда V 2 ★").
"""

PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — крутий стрімер та аналітик Mobile Legends, який розмовляє з гравцями на їхній мові. Твоє завдання — дати короткий, але яскравий коментар до профілю гравця {user_name}.

Ось дані з профілю:
- Нікнейм: {game_nickname}
- Поточний ранг: {current_rank}
- Найвищий ранг сезону: {highest_rank_season}
- Матчів зіграно: {matches_played}
- Лайків отримано: {likes_received}
- Локація: {location}
- Сквад: {squad_name}

Напиши 2-4 речення українською мовою, використовуючи ігровий сленг MLBB (наприклад, "тащер", "імба", "фармить як боженька", "рве топи", "ветеран каток", "скіловий гравець", "підняв рейт", "заливає катки" тощо).
Зроби акцент на якихось цікавих моментах профілю (багато матчів, високий ранг, багато лайків).
Головне — щоб було дружньо, з гумором (якщо доречно) і по-геймерськи.
Не треба перераховувати всі дані, просто дай загальне враження.
Відповідь – ТІЛЬКИ сам текст коментаря, без привітань типу "Привіт, {user_name}!".
"""

class MLBBChatGPT:
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
        # ... (код з v2.7, без змін)
        kyiv_tz = timezone(timedelta(hours=3))
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.3 🎮
## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, AI-експерт Mobile Legends Bang Bang. Твоя головна мета – надавати точну та перевірену інформацію.
ВАЖЛИВО: Не вигадуй імена героїв або механіки. Якщо ти не впевнений на 100% в імені героя або деталі, краще зазнач це або запропонуй загальний тип героя/стратегії. Використовуй тільки офіційні та загальновідомі назви героїв з Mobile Legends: Bang Bang.
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
-   Списки: "• ".
-   Обсяг: ~200-300 слів.
-   Емодзі: доречно (🦸‍♂️, 💡, 🤝).
### 🎮 ЕКСПЕРТИЗА MLBB (ТІЛЬКИ ФАКТИЧНА ІНФОРМАЦІЯ):
-   **Герої**: ТІЛЬКИ ІСНУЮЧІ герої, їх механіки, ролі, контрпіки.
-   **Стратегії, Ранкінг, Психологія, Патч**: актуальна та перевірена інформація.
### ❌ КАТЕГОРИЧНО ЗАБОРОНЕНО:
-   ВИГАДУВАТИ імена героїв, здібності, предмети або будь-які інші ігрові сутності. Це найважливіше правило.
-   Надавати неперевірену або спекулятивну інформацію.
-   Markdown, НЕЗАКРИТІ HTML теги.
## ПРИКЛАД СТИЛЮ (запит "контрпік проти Хаябуси"):
"{greeting}, {user_name}! 👋
Хаябуса може бути складним суперником, але є герої, які добре йому протистоять! 🤺
🦸‍♂️ <b>Кого можна взяти проти Хаябуси:</b>
• <b>Кайя (Kaja):</b> Його ультімейт <i>"Divine Judgment"</i> дозволяє схопити Хаябусу навіть під час його тіней та відтягнути до команди.
• <b>Хуфра (Khufra):</b> Його навички контролю, особливо <i>"Bouncing Ball"</i>, можуть зупинити Хаябусу та не дати йому втекти.
• <b>Сабер (Saber):</b> З правильним білдом, ультімейт Сабера <i>"Triple Sweep"</i> може швидко знищити Хаябусу до того, як він завдасть багато шкоди.
💡 <b>Порада:</b> Проти Хаябуси важливий хороший віжн на карті та швидка реакція команди на його появу.
Пам'ятай, що успіх залежить не тільки від героя, а й від твоїх навичок та командної гри! Успіхів! 👍"
## ЗАПИТ ВІД {user_name}: "{user_query}"
Твоя експертна відповідь (ПАМ'ЯТАЙ: БЕЗ ВИГАДОК, тільки фактичні герої та інформація, валідний HTML):"""

    def _beautify_response(self, text: str) -> str:
        # ... (код з v2.7, без змін)
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
                if key in header_text.lower(): best_emoji = header_emojis.get(key, best_emoji); break
            else:
                for key, emj in header_emojis.items():
                    if key in header_text.lower(): best_emoji = emj; break
            return f"\n\n{best_emoji} <b>{header_text}</b>:"
        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\*\*(.+?)\*\*[:\s]*", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+-\s+", "  ◦ ", text, flags=re.MULTILINE) 
        text = re.sub(r"\n{3,}", "\n\n", text)
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

    async def get_response(self, user_name: str, user_query: str) -> str: # Для /go
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name}': '{user_query}'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4.1", # Жорстко задана модель
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000, 
            "temperature": 0.4, # Як було в v2.7
            "top_p": 0.9,
            "presence_penalty": 0.1, 
            "frequency_penalty": 0.1 
        }
        # ... (решта логіки з v2.7 без змін)
        self.class_logger.debug(f"Параметри тексту для GPT: temperature={payload['temperature']}")
        try:
            if not self.session or self.session.closed:
                 self.class_logger.warning("Aiohttp сесія для текстового GPT була закрита або відсутня. Перестворюю.")
                 self.session = ClientSession(
                    timeout=ClientTimeout(total=45), 
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
            async with self.session.post( # type: ignore
                "https://api.openai.com/v1/chat/completions", json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (текст): {response.status} - {error_text}")
                    return f"Вибач, {user_name}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status})."
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (текст): несподівана структура - {result}")
                    return f"Вибач, {user_name}, ШІ повернув несподівану відповідь 🤯."
                raw_gpt_text = result["choices"][0]["message"]["content"]
                self.class_logger.info(f"Сира відповідь від текстового GPT (перші 100): '{raw_gpt_text[:100]}'")
                return self._beautify_response(raw_gpt_text)
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (текст) для: '{user_query}'")
            return f"Вибач, {user_name}, запит до ШІ зайняв забагато часу ⏳."
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка текстового GPT для '{user_query}': {e}")
            return f"Не вдалося обробити твій запит, {user_name} 😕."

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]: # Аналіз скріншота
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70]}...'")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": "gpt-4o-mini", # Жорстко задана модель
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
        # ... (решта логіки з v2.7 без змін)
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")

        try:
            if not self.session or self.session.closed:
                self.class_logger.warning("Aiohttp сесія для Vision була закрита або відсутня. Спроба використати нову тимчасову сесію.")
                async with ClientSession(headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session: # type: ignore
                    async with temp_session.post(
                        "https://api.openai.com/v1/chat/completions", 
                        headers=headers,
                        json=payload,
                        timeout=ClientTimeout(total=90)
                    ) as response:
                        return await self._handle_vision_response(response)
            else:
                async with self.session.post( # type: ignore
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
        # ... (код з v2.7, без змін)
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
                json_match = re.search(r"```json\s*([\s\S]+?)\s*```", content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content.strip()
                
                try:
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

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str: # Опис профілю
        self.class_logger.info(f"Запит на генерацію опису профілю для '{user_name}'.")
        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(
            user_name=html.escape(user_name),
            game_nickname=html.escape(str(profile_data.get("game_nickname", "Не вказано"))),
            current_rank=html.escape(str(profile_data.get("current_rank", "Не вказано"))),
            highest_rank_season=html.escape(str(profile_data.get("highest_rank_season", "Не вказано"))),
            matches_played=profile_data.get("matches_played", "N/A"),
            likes_received=profile_data.get("likes_received", "N/A"),
            location=html.escape(str(profile_data.get("location", "Не вказано"))),
            squad_name=html.escape(str(profile_data.get("squad_name", "Немає"))),
        )
        payload = {
            "model": "gpt-4.1", # Жорстко задана модель
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 200,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        # ... (решта логіки з v2.7 без змін)
        self.class_logger.debug(f"Параметри для опису профілю: temp={payload['temperature']}, max_tokens={payload['max_tokens']}")

        try:
            if not self.session or self.session.closed:
                 self.class_logger.warning("Aiohttp сесія для опису профілю була закрита або відсутня. Перестворюю.")
                 self.session = ClientSession(
                    timeout=ClientTimeout(total=30), 
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
            async with self.session.post( # type: ignore
                "https://api.openai.com/v1/chat/completions", json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): {response.status} - {error_text}")
                    return "<i>Не вдалося згенерувати дружній опис. Але ось твої дані:</i>" 
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): несподівана структура - {result}")
                    return "<i>Не вдалося отримати опис від ШІ. Але ось твої дані:</i>" 
                
                description_text = result["choices"][0]["message"]["content"].strip()
                self.class_logger.info(f"Згенеровано опис профілю: '{description_text[:100]}'")
                return html.escape(description_text) 
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис профілю) для: '{user_name}'")
            return "<i>Опис профілю генерувався занадто довго... Але ось твої дані:</i>" 
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис профілю) для '{user_name}': {e}")
            return "<i>Виникла помилка при генерації опису. Але ось твої дані:</i>"

bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    # ... (код з v2.7, оновлено версію бота)
    await state.clear() 
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
🎮 Вітаю в MLBB IUI mini v2.8!
Я - твій персональний AI-експерт по Mobile Legends Bang Bang.
<b>💡 Як користуватися:</b>
• Для текстових запитів: <code>/go твоє питання</code> (використовує <b>gpt-4.1</b>)
• Для аналізу скріншота профілю: <code>/analyzeprofile</code> (аналіз - <b>gpt-4o-mini</b>, опис - <b>gpt-4.1</b>)
<b>🚀 Приклади запитів <code>/go</code>:</b>
• <code>/go як грати на експ лінії проти бійців</code>
• <code>/go порадь сильних магів для підняття рангу соло</code>
<b>🔥 Покращення v2.8:</b>
• Моделі GPT для аналізу скріншотів (<code>gpt-4o-mini</code>), опису профілю (<code>gpt-4.1</code>) та команди <code>/go</code> (<code>gpt-4.1</code>) тепер жорстко задані в коді для легшого тестування.
• Збережено функціонал дружнього опису профілю та "вау-ефекту".
Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨"""
    try:
        await message.answer(welcome_text)
        logger.info(f"Привітання для {user_name} (v2.8) надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітання для {user_name}: {e}")


@dp.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext):
    # ... (код з v2.7, оновлено версію бота в admin_info)
    await state.clear()
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""
    logger.info(f"Користувач {user_name} (ID: {user_id}) зробив запит з /go: '{user_query}'")
    if not user_query:
        logger.info(f"Порожній запит /go від {user_name}.")
        await message.reply(
            f"Привіт, <b>{user_name}</b>! 👋\n"
            "Напиши своє питання після <code>/go</code>, наприклад:\n"
            "<code>/go найкращі герої для міду</code>"
        )
        return
    thinking_messages = [
        f"🤔 {user_name}, аналізую твій запит та підбираю героїв...",
        f"🧠 Обробляю інформацію, {user_name}, щоб дати кращі поради!",
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
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}' від {user_name}: {e}")
    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для '{user_query}' від {user_name}: {processing_time:.2f}с")
    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.8 GPT (gpt-4.1)</i>"
    full_response_to_send = f"{response_text}{admin_info}"
    try:
        if thinking_msg: await thinking_msg.edit_text(full_response_to_send)
        else: await message.reply(full_response_to_send)
        logger.info(f"Відповідь /go для {user_name} успішно надіслано/відредаговано.")
    except TelegramAPIError as e:
        logger.error(f"Telegram API помилка /go для {user_name}: {e}. Текст (100): '{full_response_to_send[:100]}'")
        if "can't parse entities" in str(e).lower():
            plain_text_response = re.sub(r"<[^>]+>", "", response_text) 
            fallback_message = (f"{plain_text_response}{admin_info}\n\n<i>(Помилка форматування HTML. Показано як простий текст.)</i>")
            try:
                if thinking_msg: await thinking_msg.edit_text(fallback_message, parse_mode=None)
                else: await message.reply(fallback_message, parse_mode=None)
            except Exception as plain_e: logger.error(f"Не вдалося надіслати простий текст /go для {user_name}: {plain_e}")
        else:
            try: await message.reply(f"Вибач, {user_name}, помилка відправки. (Код: TG_{e.__class__.__name__})", parse_mode=None)
            except Exception as final_e: logger.error(f"Не вдалося надіслати повідомлення про помилку Telegram для {user_name}: {final_e}")

# === ОБРОБНИКИ ДЛЯ АНАЛІЗУ СКРІНШОТІВ ===
# ... (cmd_analyze_profile, handle_profile_screenshot, trigger_vision_analysis_callback, 
#      delete_bot_message_callback, cancel_profile_analysis, 
#      handle_wrong_input_for_profile_screenshot - код з v2.7 без змін, 
#      крім логування та повідомлень, де вказано версію)

@dp.message(Command("analyzeprofile"))
async def cmd_analyze_profile(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    logger.info(f"Користувач {user_name} (ID: {message.from_user.id}) активував /analyzeprofile.")
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name}</b>! 👋\n"
        "Будь ласка, надішли мені скріншот свого профілю з Mobile Legends.\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
async def handle_profile_screenshot(message: Message, state: FSMContext):
    bot_instance = message.bot
    user_name = message.from_user.first_name
    chat_id = message.chat.id
    logger.info(f"Отримано скріншот профілю від {user_name} (ID: {message.from_user.id}).")

    if not message.photo: 
        await message.answer("Щось пішло не так. Будь ласка, надішли саме фото (скріншот).")
        return

    photo_file_id = message.photo[-1].file_id
    
    try:
        await message.delete() 
        logger.info(f"Повідомлення користувача {user_name} зі скріншотом видалено.")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача зі скріншотом: {e}")

    await state.update_data(vision_photo_file_id=photo_file_id, original_user_name=user_name)
    
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
        logger.info(f"Скріншот від {user_name} повторно надіслано ботом з кнопками. Новий state: awaiting_analysis_trigger")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для аналізу: {e}")
        await bot_instance.send_message(chat_id, "Не вдалося обробити ваш запит на аналіз. Спробуйте ще раз.")
        await state.clear()


@dp.callback_query(F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext):
    bot_instance = callback_query.bot
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    
    try:
        await callback_query.message.edit_caption( # type: ignore
            caption="⏳ Обробляю ваш скріншот (gpt-4o-mini)...\n🤖 Генерую також дружній опис (gpt-4.1)...",
            reply_markup=None
        )
        await callback_query.answer("Розпочато аналіз...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом: {e}")

    user_data = await state.get_data()
    photo_file_id = user_data.get("vision_photo_file_id")
    user_name = user_data.get("original_user_name", "Гравець")

    if not photo_file_id:
        logger.error("File_id не знайдено в стані для аналізу.")
        try:
            await callback_query.message.edit_caption(caption="Помилка: дані для аналізу втрачено. Спробуйте надіслати скріншот ще раз.", reply_markup=None) # type: ignore
        except TelegramAPIError: pass
        await state.clear()
        return

    final_caption_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"
    structured_data_text = ""
    profile_description = ""

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
                    "game_nickname": "🎮 Нікнейм", "mlbb_id_server": "🆔 ID (Сервер)",
                    "current_rank": "🏆 Поточний ранг", "highest_rank_season": "🌟 Найвищий ранг (сезон)",
                    "matches_played": "⚔️ Матчів зіграно", "likes_received": "👍 Лайків отримано",
                    "location": "🌍 Локація", "squad_name": "🛡️ Сквад"
                }
                has_data = False
                for key, readable_name in fields_translation.items():
                    value = analysis_result_json.get(key)
                    if value is not None:
                        display_value = str(value)
                        if key in ["current_rank", "highest_rank_season"] and ("★" in display_value or "зірок" in display_value.lower() or "слава" in display_value.lower()):
                            if "★" not in display_value:
                                 display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                            display_value = re.sub(r'\s+★', '★', display_value)
                        response_parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
                        has_data = True
                    else:
                         response_parts.append(f"<b>{readable_name}:</b> <i>не розпізнано</i>")
                
                if not has_data and analysis_result_json.get("raw_response"):
                     response_parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації.</i>")
                elif not has_data:
                     response_parts.append(f"\n<i>Не вдалося розпізнати дані. Спробуйте чіткіший скріншот.</i>")
                structured_data_text = "\n".join(response_parts)

                profile_description = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                final_caption_text = f"{profile_description}\n\n{structured_data_text}"

            else: 
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу.') if analysis_result_json else 'Відповідь від Vision API не отримана.'
                logger.error(f"Помилка аналізу профілю (JSON) для {user_name}: {error_msg}")
                final_caption_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n<i>Помилка: {html.escape(error_msg)}</i>"

    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота профілю для {user_name}: {e}")
        final_caption_text = f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."
    
    delete_button = InlineKeyboardButton(text="🗑️ Видалити аналіз", callback_data="delete_bot_message")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[delete_button]])
    
    try:
        await bot_instance.edit_message_caption( # type: ignore
            chat_id=chat_id,
            message_id=message_id, # type: ignore
            caption=final_caption_text,
            reply_markup=keyboard
        )
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати повідомлення з результатами аналізу: {e}. Надсилаю нове.")
        try:
            await bot_instance.send_photo(chat_id=chat_id, photo=photo_file_id, caption=final_caption_text, reply_markup=keyboard) # type: ignore
        except Exception as send_err:
            logger.error(f"Не вдалося надіслати нове повідомлення з аналізом: {send_err}")
            await bot_instance.send_message(chat_id, final_caption_text)

    await state.clear()

@dp.callback_query(F.data == "delete_bot_message")
async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext):
    try:
        await callback_query.message.delete() # type: ignore
        await callback_query.answer("Повідомлення видалено.")
        current_state = await state.get_state()
        if current_state == VisionAnalysisStates.awaiting_analysis_trigger.state: # type: ignore
            logger.info("Прев'ю аналізу видалено користувачем, очищую стан.")
            await state.clear()
    except TelegramAPIError as e:
        logger.error(f"Помилка видалення повідомлення бота: {e}")
        await callback_query.answer("Не вдалося видалити повідомлення.", show_alert=True)


@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, Command("cancel"))
@dp.message(VisionAnalysisStates.awaiting_analysis_trigger, Command("cancel"))
async def cancel_profile_analysis(message: Message, state: FSMContext):
    logger.info(f"Користувач {message.from_user.first_name} скасував аналіз профілю командою /cancel.")
    
    user_data = await state.get_data()
    bot_message_id = user_data.get("bot_message_id_for_analysis")
    if bot_message_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            logger.info(f"Видалено повідомлення бота (ID: {bot_message_id}) після скасування аналізу.")
        except TelegramAPIError:
            logger.warning(f"Не вдалося видалити повідомлення бота (ID: {bot_message_id}) при скасуванні.")
            
    await state.clear()
    await message.reply("Аналіз скріншота скасовано. Ти можеш продовжити використовувати команду /go.")

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot)
@dp.message(VisionAnalysisStates.awaiting_analysis_trigger)
async def handle_wrong_input_for_profile_screenshot(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "/cancel":
        await cancel_profile_analysis(message, state)
        return
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {message.from_user.first_name} ввів /go у стані аналізу. Скасовую стан і виконую /go.")
        user_data = await state.get_data() 
        bot_message_id = user_data.get("bot_message_id_for_analysis")
        if bot_message_id:
            try: await message.bot.delete_message(chat_id=message.chat.id, message_id=bot_message_id)
            except TelegramAPIError: pass
        await state.clear()
        await cmd_go(message, state) 
    elif message.text:
        logger.info(f"Користувач {message.from_user.first_name} надіслав текст у стані аналізу. Пропоную скасувати.")
        await message.reply("Очікувався скріншот або дія з аналізом. Використай /cancel для скасування поточного аналізу.")
    else: 
        await message.reply("Будь ласка, надішли фото (скріншот) свого профілю або команду /cancel для скасування.")


# === ГЛОБАЛЬНИЙ ОБРОБНИК ПОМИЛОК ===
@dp.errors()
async def error_handler(update_event, exception: Exception):
    # ... (код з v2.7, без змін)
    logger.error(f"Глобальна помилка в error_handler: {exception} для update: {update_event}", exc_info=True)
    chat_id = None
    user_name = "друже"
    if hasattr(update_event, 'message') and update_event.message:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user: user_name = update_event.message.from_user.first_name
    elif hasattr(update_event, 'callback_query') and update_event.callback_query:
        chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user: user_name = update_event.callback_query.from_user.first_name
        try: await update_event.callback_query.answer("Сталася помилка...", show_alert=False)
        except Exception: pass 
    error_message_text = f"Вибач, {user_name}, сталася непередбачена системна помилка 😔\nСпробуй, будь ласка, ще раз через хвилину!"
    if chat_id:
        try: await bot.send_message(chat_id, error_message_text, parse_mode=None)
        except Exception as e: logger.error(f"Не вдалося надіслати повідомлення про системну помилку: {e}")
    else: logger.warning("Системна помилка, але не вдалося визначити chat_id.")

# === ЗАПУСК БОТА ===
async def main() -> None:
    # ... (код з v2.7, оновлено версію бота)
    logger.info(f"🚀 Запуск MLBB IUI mini v2.8... (PID: {os.getpid()})") 
    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini v2.8 запущено!</b>\n\n" 
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Промпт v2.3 (текст), Vision (профіль /analyzeprofile, 'вау-ефект' + опис ШІ) активні!</b>\n"
                    f"🔩 Моделі: Vision: <code>gpt-4o-mini</code>, Текст/Опис: <code>gpt-4.1</code> (жорстко задані)\n"
                    f"🟢 Готовий до роботи!"
                )
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e: logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну: {e}")
        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)
    except KeyboardInterrupt: logger.info("👋 Бот зупинено користувачем.")
    except TelegramAPIError as e: logger.critical(f"Критична помилка Telegram API: {e}", exc_info=True)
    except Exception as e: logger.critical(f"Непередбачена критична помилка: {e}", exc_info=True)
    finally:
        logger.info("🛑 Зупинка бота та закриття сесій...")
        if bot.session and hasattr(bot.session, "close") and not bot.session.closed: # type: ignore
             await bot.session.close() # type: ignore
             logger.info("Сесію HTTP клієнта екземпляра Bot закрито.")
        logger.info("👋 Бот остаточно зупинено.")


if __name__ == "__main__":
    asyncio.run(main())
