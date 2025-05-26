"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано функціонал аналізу скріншотів профілю гравця з "вау-ефектом" та описом від ШІ.
Моделі GPT жорстко встановлені в коді. Оновлено промпти для /go та Vision.

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

# Промпт для Vision API (з версії 42b0af22f24275ac7fd499dad0d6e7621c7e7268)
PROFILE_SCREENSHOT_PROMPT = """
Проаналізуй цей скріншот профілю гравця Mobile Legends: Bang Bang.
Витягни таку інформацію та поверни її у вигляді JSON об'єкта:
- "game_nickname": Ігровий нікнейм гравця (string).
- "mlbb_id_server": ID гравця та сервер у форматі "ID (SERVER)" (string). Наприклад, "123456789 (1234)".
- "current_rank": Поточний ранг гравця (string). Наприклад, "Епічний V", "Легенда III", "Міфічний 10 зірок".
- "highest_rank_season": Найвищий ранг гравця в цьому сезоні (string). Наприклад, "Міфічна Слава 267 зірок".
- "matches_played": Кількість зіграних матчів (integer).
- "win_rate_all_matches": Відсоток перемог за всі матчі (float, наприклад 55.6). Якщо не видно, став null.
- "likes_received": Кількість отриманих лайків (integer).
- "favorite_hero_1_name": Ім'я першого улюбленого героя (string).
- "favorite_hero_1_matches": Кількість матчів на першому улюбленому герої (integer).
- "favorite_hero_1_wr": Відсоток перемог на першому улюбленому герої (float).
- "favorite_hero_2_name": Ім'я другого улюбленого героя (string).
- "favorite_hero_2_matches": Кількість матчів на другому улюбленому герої (integer).
- "favorite_hero_2_wr": Відсоток перемог на другому улюбленому герої (float).
- "favorite_hero_3_name": Ім'я третього улюбленого героя (string).
- "favorite_hero_3_matches": Кількість матчів на третьому улюбленому герої (integer).
- "favorite_hero_3_wr": Відсоток перемог на третьому улюбленому герої (float).
- "squad_name": Назва скваду (string), якщо є.
- "location": Локація гравця, якщо вказана (string).

ВАЖЛИВО:
1. Повертай ТІЛЬКИ валідний JSON. Жодного тексту до або після JSON.
2. Якщо якась інформація відсутня на скріншоті, використовуй значення null для відповідного поля.
3. Будь максимально точним з цифрами. Для рангів із зірками, вказуй кількість зірок (наприклад, "Міфічний 111 ★" або "Міфічна Слава 1026 ★").
4. Розпізнавай текст уважно, навіть якщо він невеликий.
"""

# Промпт для генерації "людського" опису профілю (з версії v2.7/v2.8)
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

    # Промпт для /go (з версії eb838b6781470a7c1c21b9c84626a716124aa967)
    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        kyiv_tz = timezone(timedelta(hours=3))
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
                   "Доброго дня" if 12 <= current_hour < 17 else \
                   "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
        return f"""Ти — IUI, експерт Mobile Legends Bang Bang.
Твоя мета — надавати гравцю {user_name} максимально корисні, точні, конкретні та мотивуючі відповіді українською мовою.
Завжди дотримуйся стандартів якості, наведених нижче.

# КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
- Платформа: Telegram (підтримує HTML, тому ВАЖЛИВО генерувати ВАЛІДНИЙ HTML з коректно закритими тегами <b>, <i>, <code>).

# СТАНДАРТИ ЯКОСТІ ВІДПОВІДЕЙ

## 🎯 СТРУКТУРА ТА ЗМІСТ:
1.  **Привітання**: Починай з "{greeting}, {user_name}! 👋"
2.  **Основна відповідь**:
    *   Чітка, конкретна інформація по суті запиту.
    *   Якщо запит стосується вибору героїв, стратегій, ролей або гри на певній лінії (наприклад, "як грати на експі", "кого взяти в мід", "контрпік проти Франко"):
        *   ОБОВ'ЯЗКОВО запропонуй 2-3 ІСНУЮЧИХ, АКТУАЛЬНИХ героїв Mobile Legends, які підходять під запит.
        *   Коротко поясни, чому ці герої є хорошим вибором (їхні ключові переваги, роль у команді, сильні сторони в контексті запиту).
        *   Якщо доречно, згадай про можливі ефективні комбінації цих героїв з іншими або про синергію.
3.  **Практичні поради**: Декілька дієвих порад, що робити гравцю для досягнення успіху.
4.  **Мотивація**: Завершуй позитивним та підбадьорюючим коментарем.

## 📝 ФОРМАТУВАННЯ (ВАЛІДНИЙ HTML):
-   Використовуй ТІЛЬКИ HTML теги: <b>для жирного тексту</b>, <i>для курсиву</i>, <code>для коду або назв героїв/предметів</code>. УСІ ТЕГИ ПОВИННІ БУТИ КОРЕКТНО ЗАКРИТІ.
-   Списки оформлюй за допомогою маркера "• " на початку кожного пункту (з пробілом після маркера).
-   Відповідь має бути структурованою, легкою для читання, обсягом приблизно 200-300 слів.
-   Використовуй доречні емодзі для покращення візуального сприйняття (наприклад, 🦸‍♂️ для героїв, 💡 для порад, 🛡️ для танків, ⚔️ для бійців, 🎯 для стрільців, 🧙 для магів, 💨 для вбивць, 🤝 для командної гри).

## 🎮 ЕКСПЕРТИЗА MLBB:
-   **Герої**: Глибоке знання всіх героїв, їхніх механік, ролей, сильних та слабких сторін, актуальних контрпіків, синергії та героїв, які зараз у меті. Завжди пропонуй тільки існуючих героїв.
-   **Предмети та Емблеми**: Загальне розуміння, але не фокусуйся на детальних білдах, оскільки вони швидко змінюються. Краще давай поради щодо стилю гри.
-   **Стратегії**: Розуміння лайнінгу, ротацій, контролю об'єктів (Черепаха, Лорд), тімфайт-тактик, макро- та мікро-гри.
-   **Рангінг та Психологія**: Поради щодо підняття рангу, важливості комунікації, позитивного настрою та контролю тільту.
-   **Поточний патч**: Намагайся враховувати актуальні зміни в грі, мету та баланс героїв.

## ❌ УНИКАЙ:
-   Використання Markdown форматування.
-   Надсилання НЕЗАКРИТИХ або некоректних HTML тегів (це спричиняє помилки відображення в Telegram).
-   Надто детальних інструкцій по білдах (предмети/емблеми).
-   Довгих, монотонних блоків тексту без абзаців та списків.
-   Вигадування неіснуючих героїв, механік або предметів.

## ПРИКЛАД СТИЛЮ ТА СТРУКТУРИ ВІДПОВІДІ (на запит "кого взяти проти Хаябуси?"):

"{greeting}, {user_name}! 👋

Хаябуса може бути справжнім головним болем, але є герої, які чудово йо_ッピング йому протистоять! 🤺

🦸‍♂️ <b>Ось декілька ефективних контрпіків:</b>
• <code>Кайя</code>: Його ультімейт <i>"Божественний Суд"</i> дозволяє схопити Хаябусу навіть під час його тіней та відтягнути до команди для швидкого знищення. 🛡️
• <code>Хуфра</code>: Його навички контролю, особливо друга навичка <i>"Стрибаючий М'яч"</i>, можуть зупинити ривки Хаябуси та не дати йому втекти або атакувати. 💨
• <code>Сабер</code>: З правильним білдом на проникнення, ультімейт Сабера <i>"Потрійний Замах"</i> може миттєво знищити Хаябусу, особливо на ранніх та середніх стадіях гри. ⚔️

💡 <b>Ключові поради проти Хаябуси:</b>
• Намагайтеся контролювати його бафи, особливо на початку гри.
• Купуйте предмети на захист, такі як <i>"Зимовий Жезл"</i> для магів або <i>"Безсмертя"</i>.
• Важливий хороший віжн на карті, щоб бачити його переміщення.

🤝 <b>Щодо командної гри:</b> Координуйте свої дії, щоб ловити Хаябусу разом. Герої з масовим контролем, як <i>Атлас</i> або <i>Лоліта</i>, також можуть бути дуже корисними.

Пам'ятай, що успіх залежить не тільки від вибору героя, а й від твоїх навичок та командної гри! Успіхів на полях битв! 👍"

# ЗАПИТ ВІД {user_name}:
"{user_query}"

Твоя експертна відповідь (дотримуйся стандартів вище, особливо щодо ВАЛІДНОГО HTML та надання прикладів героїв):
"""

    def _beautify_response(self, text: str) -> str:
        # ... (код з v2.8, без змін)
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
            "model": "gpt-4.1", 
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000, 
            "temperature": 0.65, # Як було в старому промпті /go
            "top_p": 0.9,
            "presence_penalty": 0.3, 
            "frequency_penalty": 0.2 
        }
        # ... (решта логіки з v2.8 без змін)
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
            "model": "gpt-4o-mini", 
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}, # Використовуємо переданий PROFILE_SCREENSHOT_PROMPT
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            "max_tokens": 1500, # Як було
            "temperature": 0.2 # Як було для Vision у старій версії промпту (42b0af22)
        }
        # ... (решта логіки з v2.8 без змін)
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
        # ... (код з v2.8, без змін)
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
            "model": "gpt-4.1", 
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 200,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        # ... (решта логіки з v2.8 без змін)
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
    
    # Спрощене вітальне повідомлення
    welcome_text = f"""
{greeting_msg}, <b>{user_name}</b>! {emoji}

🎮 Вітаю в MLBB IUI mini v2.9!
Я - твій персональний AI-експерт по Mobile Legends Bang Bang.

<b>💡 Можливості бота:</b>
• <b>Текстові поради:</b> Запитуй будь-що про гру через команду <code>/go твоє питання</code>.
• <b>Аналіз профілю:</b> Надішли скріншот свого профілю після команди <code>/analyzeprofile</code>, і я його проаналізую та дам дружній коментар!

<b>🚀 Приклади запитів <code>/go</code>:</b>
• <code>/go як грати на експ лінії проти бійців</code>
• <code>/go порадь сильних магів для підняття рангу соло</code>

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    try:
        await message.answer(welcome_text)
        logger.info(f"Привітання для {user_name} (v2.9) надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітання для {user_name}: {e}")

@dp.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext):
    # ... (код з v2.8, оновлено версію бота в admin_info)
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
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.9 GPT (gpt-4.1)</i>" # Зазначено модель
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
#      handle_wrong_input_for_profile_screenshot - код з v2.8 без змін, 
#      крім логування та повідомлень, де вказано версію та моделі)

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
            # Використовуємо глобальний PROFILE_SCREENSHOT_PROMPT
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, PROFILE_SCREENSHOT_PROMPT) 
            
            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"Успішний аналіз профілю (JSON) для {user_name}: {analysis_result_json}")
                # Оновлений список полів для виводу відповідно до нового Vision промпту
                response_parts = [f"<b>Детальний аналіз твого профілю, {user_name}:</b>"]
                fields_translation = {
                    "game_nickname": "🎮 Нікнейм", "mlbb_id_server": "🆔 ID (Сервер)",
                    "current_rank": "🏆 Поточний ранг", "highest_rank_season": "🌟 Найвищий ранг (сезон)",
                    "matches_played": "⚔️ Матчів зіграно", 
                    "win_rate_all_matches": "📊 Загальний вінрейт",
                    "likes_received": "👍 Лайків отримано",
                    "favorite_hero_1_name": "🥇 Топ 1 герой",
                    "favorite_hero_1_matches": "⚔️ Матчів (Топ 1)",
                    "favorite_hero_1_wr": "📊 WR (Топ 1)",
                    "favorite_hero_2_name": "🥈 Топ 2 герой",
                    "favorite_hero_2_matches": "⚔️ Матчів (Топ 2)",
                    "favorite_hero_2_wr": "📊 WR (Топ 2)",
                    "favorite_hero_3_name": "🥉 Топ 3 герой",
                    "favorite_hero_3_matches": "⚔️ Матчів (Топ 3)",
                    "favorite_hero_3_wr": "📊 WR (Топ 3)",
                    "squad_name": "🛡️ Сквад", "location": "🌍 Локація"
                }
                has_data = False
                for key, readable_name in fields_translation.items():
                    value = analysis_result_json.get(key)
                    if value is not None:
                        display_value = str(value)
                        if "rank" in key and ("★" in display_value or "зірок" in display_value.lower() or "слава" in display_value.lower()):
                            if "★" not in display_value:
                                 display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                            display_value = re.sub(r'\s+★', '★', display_value)
                        if "_wr" in key or "win_rate" in key:
                            display_value += "%"
                        response_parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
                        has_data = True
                    # Не додаємо "не розпізнано" для кожного поля, якщо його немає, бо промпт Vision тепер має багато полів
                
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
    # ... (код з v2.8, без змін)
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
    # ... (код з v2.8, без змін)
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
    # ... (код з v2.8, без змін)
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
    # ... (код з v2.8, без змін)
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
    logger.info(f"🚀 Запуск MLBB IUI mini v2.9... (PID: {os.getpid()})") 
    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini v2.9 запущено!</b>\n\n" 
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Оновлені промпти для /go та Vision!</b>\n"
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
