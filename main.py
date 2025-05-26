"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано функціонал аналізу скріншотів профілю гравця з "вау-ефектом" та описом від ШІ.
Моделі GPT жорстко встановлені в коді. Оновлено промпти для /go та Vision.
РЕВОЛЮЦІЙНИЙ ПРОМПТ v3.0 для надточного розпізнавання рангів та профільної інформації.

Python 3.11+ | aiogram 3.19+ | OpenAI gpt-4o-mini (Vision) + gpt-4.1 (Text)
Author: MLBB-BOSS | Date: 2025-05-26 | Vision Prompt v3.0
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Union

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

logger.info("🎯 Модель для Vision (аналіз скріншотів): gpt-4o-mini (Vision Prompt v3.0)")
logger.info("💬 Модель для текстових генерацій (/go, опис профілю): gpt-4.1")

# === СТАНИ FSM ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===
class VisionAnalysisStates(StatesGroup):
    awaiting_profile_screenshot = State()
    awaiting_analysis_trigger = State()

# === ПРОМПТИ ===

# РЕВОЛЮЦІЙНИЙ ПРОМПТ для Vision API v3.0 - максимальна точність розпізнавання
PROFILE_SCREENSHOT_PROMPT = """
🎯 ТИ — ЕКСПЕРТ-АНАЛІТИК MOBILE LEGENDS: BANG BANG 🎯

ГОЛОВНА МІСІЯ: Провести надточний аналіз скріншота профілю гравця та витягти МАКСИМУМ інформації з кожного піксела.

=== АЛГОРИТМ АНАЛІЗУ (ПОКРОКОВО) ===

🔍 КРОК 1: ВИЗНАЧЕННЯ ТИПУ СКРІНШОТА
- Переконайся, що це головний екран профілю MLBB (не матч, не магазин, не налаштування)
- Шукай характерні елементи: аватар гравця, фон, ранговий значок, статистика

🎮 КРОК 2: ІДЕНТИФІКАЦІЯ НІКНЕЙМУ
- Знаходься зазвичай зверху, біля аватара
- Може бути різного кольору: білий, золотий, синій
- Ігноруй будь-які символи кланів/гільдій

🆔 КРОК 3: ПОШУК ID ТА СЕРВЕРА  
- Формат: "123456789 (1234)" або просто "123456789"
- Зазвичай під нікнеймом, менший шрифт
- Може бути в дужках або без них

🏆 КРОК 4: АНАЛІЗ ПОТОЧНОГО РАНГУ (НАЙВАЖЛИВІШЕ!)
УВАГА! Це найскладніша частина. Дотримуйся цього алгоритму:

А) ЗНАЙДИ РАНГОВИЙ ЗНАЧОК (зазвичай ліворуч від центру)
Б) ВИЗНАЧ КАТЕГОРІЮ РАНГУ:
   • WARRIOR (Воїн) - сірий/коричневий значок
   • ELITE (Еліта) - зелений значок  
   • MASTER (Майстер) - синій значок
   • GRANDMASTER (Гранд Майстер) - фіолетовий значок
   • EPIC (Епік) - помаранчевий/золотий значок + РИМСЬКІ ЦИФРИ (V, IV, III, II, I)
   • LEGEND (Легенда) - червоний значок + РИМСЬКІ ЦИФРИ (V, IV, III, II, I)  
   • MYTHIC (Міфік) - темно-синій/фіолетовий + КІЛЬКІСТЬ ОЧОК
   • MYTHICAL GLORY (Міфічна Слава) - золотий/райдужний + КІЛЬКІСТЬ ЗІРОК (★)

В) ВИЗНАЧ ПІДРАНГ:
   - Для Епік/Легенда: римська цифра (V найнижчий, I найвищий)
   - Для Міфік: число очок (наприклад, 25 очок, 150 очок)
   - Для Міфічної Слави: кількість зірок (★)

Г) ЗНАЙДИ ПРОГРЕС У ПОТОЧНОМУ РАНЗІ:
   - Зірочки (★) для показу прогресу в межах підрангу
   - Для Епік/Легенда: 0-5 зірок
   - Лічильник може бути поруч зі значком або під ним

🌟 КРОК 5: НАЙВИЩИЙ РАНГ СЕЗОНУ
- Шукай напис "Highest Rank" або "Найвищий ранг"
- Може бути окремим блоком праворуч
- Формат аналогічний поточному рангу

⚔️ КРОК 6: СТАТИСТИКА МАТЧІВ
- Загальна кількість матчів (Total Matches)
- Може бути у вигляді "1,234" або "1234"

👍 КРОК 7: КІЛЬКІСТЬ ЛАЙКІВ  
- Зазвичай поруч з іконкою серця або пальця вгору
- Число, може бути з комами

🛡️ КРОК 8: ІНФОРМАЦІЯ ПРО СКВАД
- Назва команди/клану під нікнеймом
- Може мати спеціальні символи або теги

🌍 КРОК 9: ЛОКАЦІЯ/РЕГІОН
- Назва країни або міста
- Може бути з прапорцем

=== ФОРМАТ ВІДПОВІДІ ===
ОБОВ'ЯЗКОВО поверни ТІЛЬКИ валідний JSON без жодного додаткового тексту:

{
  "game_nickname": "точний нікнейм гравця або null",
  "mlbb_id_server": "ID (сервер) наприклад '123456789 (1234)' або null",
  "current_rank": "ТОЧНИЙ поточний ранг з усіма деталями або null",
  "highest_rank_season": "найвищий ранг сезону або null", 
  "matches_played": число_матчів_або_null,
  "likes_received": число_лайків_або_null,
  "squad_name": "назва скваду або null",
  "location": "локація гравця або null",
  "additional_info": {
    "avatar_border": "тип рамки аватара або null",
    "title": "титул гравця або null", 
    "vip_level": "VIP рівень або null",
    "battle_points": "кількість BP або null",
    "diamonds": "кількість діамантів або null",
    "tickets": "кількість квитків або null"
  }
}

=== ПРИКЛАДИ ПРАВИЛЬНОГО РОЗПІЗНАВАННЯ РАНГІВ ===

✅ ПРАВИЛЬНО:
- "Епік V 3★" (Епік п'ятий рівень, 3 зірки прогресу)
- "Легенда II 1★" (Легенда другий рівень, 1 зірка)
- "Міфік 25 очок" (Міфік з 25 очками)
- "Міфічна Слава 150★" (Міфічна Слава зі 150 зірками)

❌ НЕПРАВИЛЬНО:
- "Епік X" (римської цифри X в Епіку не існує)
- "Легенда VII" (максимум V рівнів)
- "Міфічна Слава очок" (має бути зірки ★)

=== ОСОБЛИВІ ІНСТРУКЦІЇ ===

🎯 ПРІОРИТЕТИ ТОЧНОСТІ:
1. Поточний ранг - найважливіше!
2. Нікнейм та ID
3. Статистика та додаткова інформація

🔍 ЯКЩО ЩОСЬ НЕЧІТКО:
- Краще поставити null, ніж вгадувати
- Якщо ранг видно частково, опиши те, що точно розрізняєш

🚫 ЧОГО НЕ РОБИТИ:
- Не додавай жодного тексту окрім JSON
- Не вигадуй дані, які не видно
- Не плутай поточний та найвищий ранг
- Не ігноруй римські цифри та зірки

АНАЛІЗУЙ РЕТЕЛЬНО ТА ПОВЕРТАЙ ТОЧНИЙ JSON! 🎮
"""

# Промпт для генерації "людського" опису профілю
PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — досвідчений стрімер та аналітик Mobile Legends, який розмовляє з гравцями на їхній мові. 
Твоє завдання — дати короткий, дружній коментар до профілю гравця, використовуючи ігровий сленг.

Ось дані з профілю:
- Нікнейм: {game_nickname}
- Поточний ранг: {current_rank}
- Найвищий ранг сезону: {highest_rank_season}
- Матчів зіграно: {matches_played}
- Лайків отримано: {likes_received}
- Локація: {location}
- Сквад: {squad_name}
- Додаткова інформація: {additional_info}

Напиши 2-4 речення українською мовою з ігровим сленгом MLBB (наприклад, "тащер", "імба", "фармить", "ранк ап", "мейн"). 
Зроби акцент на цікавих моментах: високий ранг, багато матчів, круті досягнення.
Головне — щоб було дружньо, з гумором і по-геймерськи.

Відповідь — ТІЛЬКИ текст коментаря, без привітань.
"""


class MLBBChatGPT:
    """
    Удосконалений GPT асистент для MLBB з покращеним розпізнаванням скріншотів.
    
    Версії моделей:
    - Vision API: gpt-4o-mini (аналіз скріншотів)
    - Text API: gpt-4.1 (текстові відповіді та описи)
    """
    
    def __init__(self, api_key: str) -> None:
        self.api_key: str = api_key
        self.session: Optional[ClientSession] = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=60), 
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("MLBBChatGPT сесія створена")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("MLBBChatGPT сесія закрита")
        if exc_type:
            self.class_logger.error(f"Помилка в MLBBChatGPT: {exc_type} {exc_val}", exc_info=True)

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """Створює розумний промпт для текстових відповідей /go."""
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
    *   Якщо запит стосується вибору героїв, стратегій, ролей або гри на певній лінії:
        *   ОБОВ'ЯЗКОВО запропонуй 2-3 ІСНУЮЧИХ, АКТУАЛЬНИХ героїв Mobile Legends, які підходять під запит.
        *   Коротко поясни, чому ці герої є хорошим вибором (їхні ключові переваги, роль у команді).
        *   Якщо доречно, згадай про можливі ефективні комбінації цих героїв з іншими або про синергію.
3.  **Практичні поради**: Декілька дієвих порад, що робити гравцю для досягнення успіху.
4.  **Мотивація**: Завершуй позитивним та підбадьорюючим коментарем.

## 📝 ФОРМАТУВАННЯ (ВАЛІДНИЙ HTML):
-   Використовуй ТІЛЬКИ HTML теги: <b>для жирного тексту</b>, <i>для курсиву</i>, <code>для коду або назв героїв/предметів</code>. УСІ ТЕГИ ПОВИННІ БУТИ КОРЕКТНО ЗАКРИТІ!
-   Списки оформлюй за допомогою маркера "• " на початку кожного пункту (з пробілом після маркера).
-   Відповідь має бути структурованою, легкою для читання, обсягом приблизно 200-300 слів.
-   Використовуй доречні емодзі для покращення візуального сприйняття.

## 🎮 ЕКСПЕРТИЗА MLBB:
-   **Герої**: Глибоке знання всіх героїв, їхніх механік, ролей, сильних та слабких сторін, актуальних контрпіків.
-   **Стратегії**: Розуміння лайнінгу, ротацій, контролю об'єктів (Черепаха, Лорд), тімфайт-тактик.
-   **Рангінг та Психологія**: Поради щодо підняття рангу, важливості комунікації, позитивного настрою.

## ❌ УНИКАЙ:
-   Використання Markdown форматування.
-   Надсилання НЕЗАКРИТИХ або некоректних HTML тегів.
-   Вигадування неіснуючих героїв, механік або предметів.

# ЗАПИТ ВІД {user_name}:
"{user_query}"

Твоя експертна відповідь (дотримуйся стандартів вище, особливо щодо ВАЛІДНОГО HTML та надання прикладів героїв):"""

    def _beautify_response(self, text: str) -> str:
        """Оформлює текст GPT для Telegram з виправленням HTML тегів."""
        self.class_logger.debug(f"Beautify: обробка тексту довжиною {len(text)} символів")
        
        # Маппінг емодзі для заголовків
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍", "комунікація": "💬",
            "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄", "командна гра": "🤝",
            "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", "стратегі": "🎯", "мета": "🔥",
            "поточна мета": "📊", "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "💡"
        }

        def replace_header(match):
            header_text = match.group(1).strip(": ").capitalize()
            best_emoji = "💡"  # За замовчуванням
            
            # Пріоритет для більш специфічних ключів
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета"]
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else:
                # Якщо не знайдено, шукаємо серед загальних
                for key, emj in header_emojis.items():
                    if key in header_text.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>:"

        # Заміна заголовків
        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\*\*(.+?)\*\*[:\s]*", replace_header, text, flags=re.MULTILINE)
        
        # Заміна списків
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+-\s+", "  ◦ ", text, flags=re.MULTILINE)
        
        # Видалення зайвих переносів
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Заміна Markdown на HTML, якщо GPT все ж використає
        text = re.sub(r"\*\*(?P<content>.+?)\*\*", r"<b>\g<content></b>", text)
        text = re.sub(r"\*(?P<content>.+?)\*", r"<i>\g<content></i>", text)
        
        # Перевірка збалансованості тегів <b>
        open_b_count = len(re.findall(r"<b>", text))
        close_b_count = len(re.findall(r"</b>", text))

        if open_b_count > close_b_count:
            missing_tags = open_b_count - close_b_count
            self.class_logger.warning(f"Beautify: Виявлено {missing_tags} незакритих тегів <b>. Додаю їх в кінець.")
            text += "</b>" * missing_tags
        elif close_b_count > open_b_count:
            self.class_logger.warning(f"Beautify: Виявлено {close_b_count - open_b_count} зайвих тегів </b>.")

        self.class_logger.debug("Beautify: обробка завершена")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """Отримує якісну відповідь від GPT для команди /go."""
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name}': '{user_query[:50]}...'")
        
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
        
        try:
            if not self.session or self.session.closed:
                self.class_logger.warning("Сесія для текстового GPT закрита. Перестворюю.")
                self.session = ClientSession(
                    timeout=ClientTimeout(total=45), 
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (текст): {response.status} - {error_text}")
                    return f"Вибач, {user_name}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status})."
                    
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (текст): несподівана структура - {result}")
                    return f"Вибач, {user_name}, ШІ повернув несподівану відповідь 🤯."
                    
                raw_gpt_text = result["choices"][0]["message"]["content"]
                self.class_logger.info(f"Отримано відповідь від текстового GPT: {len(raw_gpt_text)} символів")
                return self._beautify_response(raw_gpt_text)
                
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (текст) для: '{user_query}'")
            return f"Вибач, {user_name}, запит до ШІ зайняв занадто багато часу ⏳."
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка текстового GPT для '{user_query}': {e}")
            return f"Не вдалося обробити твій запит, {user_name} 😕."

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Аналізує скріншот профілю з використанням Vision API v3.0.
        
        Args:
            image_base64: Зображення в форматі base64
            prompt: Промпт для аналізу
            
        Returns:
            JSON об'єкт з розпізнаними даними або помилкою
        """
        self.class_logger.info("Запуск Vision API v3.0 для аналізу скріншота")
        
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
            "max_tokens": 2000,  # Збільшено для детального аналізу
            "temperature": 0.1   # Зменшено для максимальної точності
        }
        
        self.class_logger.debug(f"Vision API параметри: модель={payload['model']}, max_tokens={payload['max_tokens']}, temp={payload['temperature']}")

        try:
            if not self.session or self.session.closed:
                self.class_logger.warning("Сесія для Vision API закрита. Створюю тимчасову сесію.")
                async with ClientSession(headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session:
                    async with temp_session.post(
                        "https://api.openai.com/v1/chat/completions", 
                        headers=headers,
                        json=payload,
                        timeout=ClientTimeout(total=120)  # Збільшено тайм-аут
                    ) as response:
                        return await self._handle_vision_response(response)
            else:
                async with self.session.post(
                    "https://api.openai.com/v1/chat/completions", 
                    headers=headers, 
                    json=payload,
                    timeout=ClientTimeout(total=120)
                ) as response:
                    return await self._handle_vision_response(response)
                    
        except asyncio.TimeoutError:
            self.class_logger.error("Vision API тайм-аут через 120 секунд")
            return {"error": "Аналіз зображення зайняв занадто багато часу. Спробуй чіткіший скріншот."}
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка Vision API: {e}")
            return {"error": f"Загальна помилка при аналізі зображення: {str(e)}"}

    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        """Обробляє відповідь від Vision API з покращеною обробкою JSON."""
        if response.status == 200:
            try:
                result = await response.json()
            except aiohttp.ContentTypeError: 
                raw_text_response = await response.text()
                self.class_logger.error(f"Vision API відповідь не є JSON. Статус: {response.status}. Відповідь: {raw_text_response[:300]}")
                return {"error": "Vision API повернуло некоректну відповідь.", "raw_response": raw_text_response}

            content = result.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                self.class_logger.info(f"Vision API відповідь отримана: {len(content)} символів")
                
                # Покращена обробка JSON відповіді
                json_str = content.strip()
                
                # Видалення можливих markdown блоків
                json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1).strip()
                
                # Очищення від зайвого тексту
                if not json_str.startswith("{"):
                    start_pos = json_str.find("{")
                    if start_pos != -1:
                        json_str = json_str[start_pos:]
                        
                if not json_str.endswith("}"):
                    end_pos = json_str.rfind("}")
                    if end_pos != -1:
                        json_str = json_str[:end_pos + 1]
                
                try:
                    parsed_json = json.loads(json_str)
                    self.class_logger.info("JSON успішно розпарсено")
                    
                    # Валідація та очистка даних
                    cleaned_data = self._validate_and_clean_profile_data(parsed_json)
                    return cleaned_data
                    
                except json.JSONDecodeError as e:
                    self.class_logger.error(f"Помилка JSON декодування: {e}. Рядок: '{json_str[:300]}'")
                    return {"error": "Не вдалося розпарсити JSON відповідь від Vision API.", "raw_response": content}
            else:
                self.class_logger.error(f"Vision API відповідь без контенту: {result}")
                return {"error": "Vision API повернуло порожню відповідь."}
        else:
            error_text = await response.text()
            self.class_logger.error(f"Vision API помилка: {response.status} - {error_text[:300]}")
            return {"error": f"Помилка Vision API: {response.status}", "details": error_text[:200]}

    def _validate_and_clean_profile_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Валідує та очищає дані профілю, отримані з Vision API.
        
        Args:
            data: Сирі дані з Vision API
            
        Returns:
            Очищені та валідовані дані
        """
        cleaned = {}
        
        # Очистка базових полів
        string_fields = ["game_nickname", "mlbb_id_server", "current_rank", "highest_rank_season", "squad_name", "location"]
        for field in string_fields:
            value = data.get(field)
            if isinstance(value, str) and value.strip() and value.lower() not in ["null", "none", "н/д", "невідомо"]:
                cleaned[field] = value.strip()
            else:
                cleaned[field] = None
        
        # Очистка числових полів
        numeric_fields = ["matches_played", "likes_received"]
        for field in numeric_fields:
            value = data.get(field)
            if isinstance(value, (int, float)) and value >= 0:
                cleaned[field] = int(value)
            elif isinstance(value, str):
                # Спроба перетворити рядок у число
                clean_str = re.sub(r'[^\d]', '', value)
                if clean_str.isdigit():
                    cleaned[field] = int(clean_str)
                else:
                    cleaned[field] = None
            else:
                cleaned[field] = None
        
        # Обробка додаткової інформації
        additional_info = data.get("additional_info", {})
        if isinstance(additional_info, dict):
            cleaned_additional = {}
            for key, value in additional_info.items():
                if value is not None and str(value).strip() and str(value).lower() not in ["null", "none"]:
                    cleaned_additional[key] = str(value).strip()
            if cleaned_additional:
                cleaned["additional_info"] = cleaned_additional
        
        self.class_logger.debug(f"Дані профілю очищено: {len(cleaned)} полів")
        return cleaned

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        """Генерує дружній опис профілю на основі розпізнаних даних."""
        self.class_logger.info(f"Генерація опису профілю для '{user_name}'")
        
        # Підготовка додаткової інформації для промпту
        additional_info_text = ""
        if "additional_info" in profile_data and profile_data["additional_info"]:
            additional_info_items = []
            for key, value in profile_data["additional_info"].items():
                additional_info_items.append(f"{key}: {value}")
            additional_info_text = ", ".join(additional_info_items)
        else:
            additional_info_text = "Немає"
        
        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(
            user_name=html.escape(user_name),
            game_nickname=html.escape(str(profile_data.get("game_nickname", "Не вказано"))),
            current_rank=html.escape(str(profile_data.get("current_rank", "Не вказано"))),
            highest_rank_season=html.escape(str(profile_data.get("highest_rank_season", "Не вказано"))),
            matches_played=profile_data.get("matches_played", "N/A"),
            likes_received=profile_data.get("likes_received", "N/A"),
            location=html.escape(str(profile_data.get("location", "Не вказано"))),
            squad_name=html.escape(str(profile_data.get("squad_name", "Немає"))),
            additional_info=html.escape(additional_info_text)
        )
        
        payload = {
            "model": "gpt-4.1", 
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 250,  # Трохи збільшено
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        
        try:
            if not self.session or self.session.closed:
                self.class_logger.warning("Сесія для опису профілю закрита. Перестворюю.")
                self.session = ClientSession(
                    timeout=ClientTimeout(total=30), 
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): {response.status} - {error_text}")
                    return "<i>Не вдалося згенерувати дружній опис. Але ось твої дані:</i>" 
                    
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): несподівана структура - {result}")
                    return "<i>Не вдалося отримати опис від ШІ. Але ось твої дані:</i>" 
                
                description_text = result["choices"][0]["message"]["content"].strip()
                self.class_logger.info(f"Згенеровано опис профілю: {len(description_text)} символів")
                return html.escape(description_text) 
                
        except asyncio.TimeoutError:
            self.class_logger.error("Тайм-аут генерації опису профілю")
            return "<i>Опис профілю генерувався занадто довго... Але ось твої дані:</i>" 
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка опису профілю для '{user_name}': {e}")
            return "<i>Виникла помилка при генерації опису. Але ось твої дані:</i>"


# === ІНІЦІАЛІЗАЦІЯ БОТА ===
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обробник команди /start з інформацією про нові можливості."""
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

🎮 Вітаю в MLBB IUI mini v3.0!
Я - твій персональний AI-експерт по Mobile Legends Bang Bang з <b>революційною</b> системою розпізнавання скріншотів!

<b>🚀 Нові можливості v3.0:</b>
• <b>🎯 Надточне розпізнавання рангів</b> - тепер розрізняю навіть римські цифри та зірки!
• <b>📊 Розширений аналіз профілю</b> - витягую максимум інформації з кожного піксела
• <b>💎 Додаткові дані</b> - VIP рівень, титули, рамки аватара та інше

<b>💡 Можливості бота:</b>
• <b>Текстові поради:</b> <code>/go твоє питання</code>
• <b>Аналіз профілю:</b> <code>/analyzeprofile</code> → надішли скріншот

<b>🏆 Приклади запитів <code>/go</code>:</b>
• <code>/go як швидко піднятися з Епіка до Легенди</code>
• <code>/go найкращі герої для соло ранкед</code>
• <code>/go стратегії проти Фанні</code>

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    
    try:
        await message.answer(welcome_text)
        logger.info(f"Привітання v3.0 надіслано для {user_name}")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітання для {user_name}: {e}")


@dp.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext):
    """Обробник команди /go для текстових запитів."""
    await state.clear()
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    user_query = message.text.replace("/go", "", 1).strip() if message.text else ""
    
    logger.info(f"Користувач {user_name} (ID: {user_id}) зробив запит з /go: '{user_query[:50]}...'")
    
    if not user_query:
        logger.info(f"Порожній запит /go від {user_name}")
        await message.reply(
            f"Привіт, <b>{user_name}</b>! 👋\n\n"
            "Напиши своє питання після <code>/go</code>, наприклад:\n"
            "• <code>/go найкращі герої для міду</code>\n"
            "• <code>/go як контрити Алдоуса</code>"
        )
        return

    thinking_messages = [
        f"🤔 {user_name}, аналізую твій запит та підбираю героїв...",
        f"🧠 Обробляю інформацію, {user_name}, щоб дати кращі поради!",
        f"⚡ Готую експертну відповідь спеціально для тебе, {user_name}!",
        f"🎯 {user_name}, шукаю найефективніші стратегії для твого запиту!"
    ]
    thinking_msg_text = thinking_messages[int(time.time()) % len(thinking_messages)]
    
    thinking_msg: Optional[Message] = None
    try:
        thinking_msg = await message.reply(thinking_msg_text)
    except Exception as e:
        logger.error(f"Не вдалося надіслати thinking_msg для {user_name}: {e}")

    start_time = time.time()
    response_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"
    
    try:
        async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
            response_text = await gpt.get_response(user_name, user_query)
    except Exception as e:
        logger.exception(f"Критична помилка MLBBChatGPT для '{user_query}' від {user_name}: {e}")

    processing_time = time.time() - start_time
    logger.info(f"Час обробки /go для {user_name}: {processing_time:.2f}с")

    # Додаткова інформація для адміна
    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v3.0 GPT-4.1</i>" 
    
    full_response_to_send = f"{response_text}{admin_info}"

    try:
        if thinking_msg: 
            await thinking_msg.edit_text(full_response_to_send)
        else: 
            await message.reply(full_response_to_send)
        logger.info(f"Відповідь /go для {user_name} успішно надіслана")
    except TelegramAPIError as e:
        logger.error(f"Telegram API помилка /go для {user_name}: {e}")
        if "can't parse entities" in str(e).lower():
            # Fallback для HTML помилок
            plain_text_response = re.sub(r"<[^>]+>", "", response_text) 
            fallback_message = f"{plain_text_response}{admin_info}\n\n<i>(Помилка форматування HTML. Показано як простий текст.)</i>"
            try:
                if thinking_msg: 
                    await thinking_msg.edit_text(fallback_message, parse_mode=None)
                else: 
                    await message.reply(fallback_message, parse_mode=None)
            except Exception as plain_e: 
                logger.error(f"Не вдалося надіслати простий текст /go для {user_name}: {plain_e}")
        else:
            try: 
                await message.reply(f"Вибач, {user_name}, помилка відправки відповіді. Спробуй ще раз.", parse_mode=None)
            except Exception as final_e: 
                logger.error(f"Не вдалося надіслати повідомлення про помилку для {user_name}: {final_e}")


# === ОБРОБНИКИ ДЛЯ АНАЛІЗУ СКРІНШОТІВ ===

@dp.message(Command("analyzeprofile"))
async def cmd_analyze_profile(message: Message, state: FSMContext):
    """Ініціює процес аналізу скріншота профілю."""
    user_name = message.from_user.first_name
    logger.info(f"Користувач {user_name} (ID: {message.from_user.id}) активував /analyzeprofile")
    
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    
    await message.reply(
        f"Привіт, <b>{user_name}</b>! 👋\n\n"
        "🎯 Надішли мені скріншот свого профілю з Mobile Legends для <b>детального аналізу v3.0</b>!\n\n"
        "<b>🔥 Що нового в v3.0:</b>\n"
        "• Надточне розпізнавання рангів та підрангів\n"
        "• Виявлення додаткової інформації (VIP, титули, діаманти)\n"
        "• Покращена обробка всіх елементів профілю\n\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )


@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
async def handle_profile_screenshot(message: Message, state: FSMContext):
    """Обробляє отриманий скріншот профілю."""
    bot_instance = message.bot
    user_name = message.from_user.first_name
    chat_id = message.chat.id
    logger.info(f"Отримано скріншот профілю від {user_name} (ID: {message.from_user.id})")

    if not message.photo: 
        await message.answer("Щось пішло не так. Будь ласка, надішли саме фото (скріншот).")
        return

    photo_file_id = message.photo[-1].file_id
    
    # Видаляємо повідомлення користувача для чистоти
    try:
        await message.delete() 
        logger.info(f"Повідомлення користувача {user_name} зі скріншотом видалено")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося видалити повідомлення користувача зі скріншотом: {e}")

    await state.update_data(vision_photo_file_id=photo_file_id, original_user_name=user_name)
    
    caption_text = "📸 Скріншот профілю отримано!\n🎯 <b>Vision API v3.0</b> готовий до аналізу.\n\nНатисніть «🔍 Аналіз» для запуску."
    
    analyze_button = InlineKeyboardButton(text="🔍 Аналіз v3.0", callback_data="trigger_vision_analysis")
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
        logger.info(f"Скріншот від {user_name} повторно надіслано ботом з кнопками v3.0")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати фото з кнопками для аналізу: {e}")
        await bot_instance.send_message(chat_id, "Не вдалося обробити ваш запит на аналіз. Спробуйте ще раз.")
        await state.clear()


@dp.callback_query(F.data == "trigger_vision_analysis", VisionAnalysisStates.awaiting_analysis_trigger)
async def trigger_vision_analysis_callback(callback_query: CallbackQuery, state: FSMContext):
    """Виконує аналіз скріншота з використанням Vision API v3.0."""
    bot_instance = callback_query.bot
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    
    try:
        await callback_query.message.edit_caption(
            caption="⏳ Аналізую скріншот за допомогою <b>Vision API v3.0</b>...\n"
                   "🧠 Обробляю деталі рангу та профільну інформацію...\n"
                   "🎨 Генерую дружній опис профілю...",
            reply_markup=None
        )
        await callback_query.answer("🚀 Запущено аналіз v3.0...")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення перед аналізом: {e}")

    user_data = await state.get_data()
    photo_file_id = user_data.get("vision_photo_file_id")
    user_name = user_data.get("original_user_name", "Гравець")

    if not photo_file_id:
        logger.error("File_id не знайдено в стані для аналізу")
        try:
            await callback_query.message.edit_caption(
                caption="❌ Помилка: дані для аналізу втрачено. Спробуйте надіслати скріншот ще раз.", 
                reply_markup=None
            )
        except TelegramAPIError: 
            pass
        await state.clear()
        return

    final_caption_text = f"Вибач, {user_name}, сталася непередбачена помилка при генерації відповіді. 😔"
    structured_data_text = ""
    profile_description = ""

    try:
        # Завантаження файлу з Telegram
        file_info = await bot_instance.get_file(photo_file_id)
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram для аналізу")
        
        downloaded_file_io = await bot_instance.download_file(file_info.file_path)
        if downloaded_file_io is None:
            raise ValueError("Не вдалося завантажити файл з Telegram для аналізу")
            
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            # Аналіз скріншота з використанням Vision API v3.0
            analysis_result_json = await gpt_analyzer.analyze_image_with_vision(image_base64, PROFILE_SCREENSHOT_PROMPT) 
            
            if analysis_result_json and "error" not in analysis_result_json:
                logger.info(f"✅ Успішний аналіз профілю v3.0 для {user_name}: {len(analysis_result_json)} полів")
                
                # Формування структурованої відповіді
                response_parts = [f"<b>🎯 Детальний аналіз твого профілю v3.0, {user_name}:</b>"]
                
                # Маппінг полів з емодзі
                fields_translation = {
                    "game_nickname": "🎮 Нікнейм", 
                    "mlbb_id_server": "🆔 ID (Сервер)",
                    "current_rank": "🏆 Поточний ранг", 
                    "highest_rank_season": "🌟 Найвищий ранг (сезон)",
                    "matches_played": "⚔️ Матчів зіграно", 
                    "likes_received": "👍 Лайків отримано",
                    "squad_name": "🛡️ Сквад", 
                    "location": "🌍 Локація"
                }
                
                has_data = False
                for key, readable_name in fields_translation.items():
                    value = analysis_result_json.get(key)
                    if value is not None: 
                        display_value = str(value)
                        
                        # Спеціальне форматування для рангів
                        if "rank" in key and ("★" in display_value or "зірок" in display_value.lower() or "слава" in display_value.lower()):
                            if "★" not in display_value:
                                display_value = display_value.replace("зірок", "★").replace("зірки", "★")
                            display_value = re.sub(r'\s+★', '★', display_value)
                        
                        response_parts.append(f"<b>{readable_name}:</b> {html.escape(display_value)}")
                        has_data = True
                
                # Додаткова інформація v3.0
                additional_info = analysis_result_json.get("additional_info", {})
                if isinstance(additional_info, dict) and additional_info:
                    response_parts.append("\n<b>💎 Додаткова інформація v3.0:</b>")
                    for key, value in additional_info.items():
                        if value:
                            key_readable = key.replace("_", " ").title()
                            response_parts.append(f"• <b>{key_readable}:</b> {html.escape(str(value))}")
                
                if not has_data:
                    response_parts.append("\n<i>😔 Не вдалося розпізнати дані з скріншота. Спробуйте чіткіший знімок профілю.</i>")
                
                structured_data_text = "\n".join(response_parts)

                # Генерація дружнього опису
                profile_description = await gpt_analyzer.get_profile_description(user_name, analysis_result_json)
                final_caption_text = f"{profile_description}\n\n{structured_data_text}"

            else: 
                error_msg = analysis_result_json.get('error', 'Невідома помилка аналізу') if analysis_result_json else 'Відповідь від Vision API не отримана'
                logger.error(f"❌ Помилка аналізу профілю v3.0 для {user_name}: {error_msg}")
                final_caption_text = f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота v3.0.\n<i>Помилка: {html.escape(error_msg)}</i>"

    except Exception as e:
        logger.exception(f"❌ Критична помилка обробки скріншота профілю для {user_name}: {e}")
        final_caption_text = f"😞 Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення."
    
    # Кнопка для видалення результату
    delete_button = InlineKeyboardButton(text="🗑️ Видалити аналіз", callback_data="delete_bot_message")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[delete_button]])
    
    try:
        await bot_instance.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=final_caption_text,
            reply_markup=keyboard
        )
        logger.info(f"✅ Результат аналізу v3.0 надіслано для {user_name}")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося відредагувати повідомлення з результатами аналізу: {e}. Надсилаю нове.")
        try:
            await bot_instance.send_photo(
                chat_id=chat_id, 
                photo=photo_file_id, 
                caption=final_caption_text, 
                reply_markup=keyboard
            )
        except Exception as send_err:
            logger.error(f"Не вдалося надіслати нове повідомлення з аналізом: {send_err}")
            await bot_instance.send_message(chat_id, final_caption_text)

    await state.clear()


@dp.callback_query(F.data == "delete_bot_message")
async def delete_bot_message_callback(callback_query: CallbackQuery, state: FSMContext):
    """Видаляє повідомлення бота з результатами аналізу."""
    try:
        await callback_query.message.delete()
        await callback_query.answer("🗑️ Повідомлення видалено.")
        
        current_state = await state.get_state()
        if current_state == VisionAnalysisStates.awaiting_analysis_trigger.state:
            logger.info("Превʼю аналізу видалено користувачем
