"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано функціонал аналізу скріншотів профілю гравця.

Python 3.11+ | aiogram 3.19+ | OpenAI gpt-4o (або аналогічна для Vision)
Author: MLBB-BOSS | Date: 2025-05-26
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

# Нові імпорти для Vision
import base64
import json
import html # для екранування HTML у відповідях

from aiogram import Bot, Dispatcher, F # Додано F для фільтрів
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
import aiohttp # Явний імпорт для type hint
from aiohttp import ClientSession, ClientTimeout # ClientTimeout вже був
from dotenv import load_dotenv

# Нові імпорти для FSM
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
# Конфігурація для Vision моделі
VISION_MODEL_NAME: str = os.getenv("VISION_MODEL_NAME", "gpt-4o")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

logger.info(f"Використовується модель для Vision: {VISION_MODEL_NAME}")

# === СТАНИ FSM ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ ===
class VisionAnalysisStates(StatesGroup):
    awaiting_profile_screenshot = State()

# === ПРОМПТ ДЛЯ АНАЛІЗУ ПРОФІЛЮ (оновлений) ===
PROFILE_SCREENSHOT_PROMPT = """
Ти — експертний аналітик гри Mobile Legends: Bang Bang.
Твоє завдання — уважно проаналізувати наданий скріншот профілю гравця.
Витягни наступну інформацію та поверни її ВИКЛЮЧНО у форматі валідного JSON об'єкта.
Не додавай жодного тексту до або після JSON, тільки сам JSON.

Структура JSON повинна бути такою:
{
  "game_nickname": "string або null, якщо не видно",
  "mlbb_id_server": "string у форматі 'ID (SERVER)' або null, якщо не видно (наприклад, '123456789 (1234)')",
  "current_rank": "string (наприклад, 'Епічний V', 'Легенда III', 'Міфічний 10 зірок') або null",
  "highest_rank_season": "string (наприклад, 'Міфічна Слава 267 зірок', 'Міфічна Слава 1111 зірок') або null",
  "matches_played": "int або null",
  "likes_received": "int або null",
  "location": "string (наприклад, 'Ukraine/Dnipropetrovs'k') або null",
  "squad_name": "string (наприклад, 'IS Iron Spirit.') або null"
}

КРИТИЧНО ВАЖЛИВІ ІНСТРУКЦІЇ ДЛЯ ТОЧНОСТІ:
1.  **Цифри та Зірки:** Дуже уважно розпізнавай УСІ цифри в показниках рангу (наприклад, '1111' зірок, а не '111'). Переконайся, що кількість цифр відповідає зображенню.
2.  **Поточний Ранг:** Це ранг, іконка якого зазвичай найбільша і розташована під блоком ID/Сервер, з підписом "Current Rank". Не плутай його з "Highest Rank" або "Mythical Glory Medal". Наприклад, якщо там іконка Епіка V, то так і пиши "Епічний V".
3.  **Найвищий Ранг Сезону:** Це ранг, іконка якого розташована біля підпису "Highest Rank". Часто він має показник зірок поруч (наприклад, ★267 або ★1111).
4.  **Відсутність Даних:** Якщо інформація (наприклад, локація) дійсно відсутня на скріншоті, використовуй null.

Будь максимально точним. Якщо якась інформація відсутня на скріншоті, використовуй значення null для відповідного поля.
Розпізнавай текст уважно, навіть якщо він невеликий або частково перекритий.
Для рангів, якщо бачиш римські цифри ТА зірки, вказуй їх разом (наприклад, "Міфічний III 15 зірок", "Легенда V 2 зірки").
"""
class MLBBChatGPT:
    """
    Спеціалізований GPT асистент для MLBB з персоналізацією та аналізом зображень.
    Відповіді структуруються, оформлюються для ідеального вигляду в Telegram.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def __aenter__(self):
        # Таймаут для сесії, може бути перекритий у конкретних запитах
        self.session = ClientSession(
            timeout=ClientTimeout(total=60), 
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
        # Код з файлу користувача, залишаємо без змін
        kyiv_tz = timezone(timedelta(hours=3))
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
        # Промпт v2.2 (або v2.3, якщо користувач оновив його у своєму файлі)
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
        # Код з файлу користувача, залишаємо без змін
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

    async def get_response(self, user_name: str, user_query: str) -> str:
        # Код з файлу користувача, з невеликими коригуваннями моделі/параметрів на основі попередніх обговорень
        self.class_logger.info(f"Запит до GPT від '{user_name}': '{user_query}'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4.1", # Або "gpt-4.1", якщо це назва конкретної версії, яку використовує користувач
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000, 
            "temperature": 0.65, # Зменшено для більшої точності, як обговорювали
            "top_p": 0.9,
            "presence_penalty": 0.3, # Значення з попередньої версії користувача
            "frequency_penalty": 0.2 # Значення з попередньої версії користувача
        }
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

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70]}...'")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": VISION_MODEL_NAME, # Використовуємо змінну з .env
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            "max_tokens": 1500,     # Вказано безпосередньо
            "temperature": 0.3      # Вказано безпосередньо для точності
        }
        self.class_logger.debug(f"Параметри для Vision API: модель={VISION_MODEL_NAME}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")

        try:
            # Перевіряємо сесію перед використанням
            if not self.session or self.session.closed:
                self.class_logger.warning("Aiohttp сесія для Vision була закрита або відсутня. Спроба використати нову тимчасову сесію.")
                # Створюємо тимчасову сесію для цього конкретного запиту
                async with ClientSession(headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session:
                    async with temp_session.post(
                        "https://api.openai.com/v1/chat/completions", 
                        headers=headers, # Повторно передаємо, бо сесія нова
                        json=payload,
                        timeout=ClientTimeout(total=90) # Таймаут для Vision запиту
                    ) as response:
                        return await self._handle_vision_response(response)
            else:
                # Використовуємо існуючу сесію класу
                async with self.session.post(
                    "https://api.openai.com/v1/chat/completions", 
                    headers=headers, # Заголовки вже є в self.session, але можна і тут для ясності
                    json=payload,
                    timeout=ClientTimeout(total=90) # Таймаут для Vision запиту
                ) as response:
                    return await self._handle_vision_response(response)
        except asyncio.TimeoutError:
            self.class_logger.error("Vision API Timeout помилка.")
            return {"error": "Запит до Vision API зайняв занадто багато часу."}
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка під час виклику Vision API: {e}")
            return {"error": f"Загальна помилка при аналізі зображення: {str(e)}"}

    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        """Допоміжна функція для обробки відповіді від Vision API."""
        if response.status == 200:
            try:
                result = await response.json()
            except aiohttp.ContentTypeError: # Обробка помилки, якщо відповідь не JSON
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
                    # Базове очищення JSON рядка
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

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
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
    welcome_text = f"""
{greeting_msg}, <b>{user_name}</b>! {emoji}
🎮 Вітаю в MLBB IUI mini v2.4!
Я - твій персональний AI-експерт по Mobile Legends Bang Bang.
<b>💡 Як користуватися:</b>
• Для текстових запитів: <code>/go твоє питання</code>
• Для аналізу скріншота профілю: <code>/analyzeprofile</code> (потім надішли скріншот)
<b>🚀 Приклади запитів <code>/go</code>:</b>
• <code>/go як грати на експ лінії проти бійців</code>
• <code>/go порадь сильних магів для підняття рангу соло</code>
<b>🔥 Покращення v2.4:</b>
• Додано аналіз скріншотів профілю!
• Оновлено логіку обробки відповідей Vision API.
• Зменшено "вигадування" неіснуючих героїв у текстових відповідях.
Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨"""
    try:
        await message.answer(welcome_text)
        logger.info(f"Привітання для {user_name} (v2.4) надіслано.")
    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати привітання для {user_name}: {e}")

@dp.message(Command("go"))
async def cmd_go(message: Message, state: FSMContext):
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
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.4 GPT (temp:0.4)</i>"
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
@dp.message(Command("analyzeprofile"))
async def cmd_analyze_profile(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    logger.info(f"Користувач {user_name} (ID: {message.from_user.id}) активував /analyzeprofile.")
    await state.set_state(VisionAnalysisStates.awaiting_profile_screenshot)
    await message.reply(
        f"Привіт, <b>{user_name}</b>! 👋\n"
        "Будь ласка, надішли мені скріншот свого профілю з Mobile Legends, і я спробую його проаналізувати.\n"
        "Якщо передумаєш, просто надішли команду /cancel."
    )

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, F.photo)
async def handle_profile_screenshot(message: Message, state: FSMContext):
    bot_instance = message.bot # Отримуємо екземпляр бота з повідомлення
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    logger.info(f"Отримано скріншот профілю від {user_name} (ID: {user_id}).")

    if not message.photo:
        await message.reply("Щось пішло не так. Будь ласка, надішли саме фото (скріншот).")
        return

    processing_msg = await message.reply("⏳ Обробляю ваш скріншот... Це може зайняти до хвилини.")
    photo = message.photo[-1]
    try:
        file_info = await bot_instance.get_file(photo.file_id)
        if not file_info.file_path:
            raise ValueError("Не вдалося отримати шлях до файлу в Telegram.")
        
        downloaded_file_io = await bot_instance.download_file(file_info.file_path)
        if downloaded_file_io is None:
            raise ValueError("Не вдалося завантажити файл з Telegram.")
            
        image_bytes = downloaded_file_io.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        async with MLBBChatGPT(OPENAI_API_KEY) as gpt_analyzer:
            analysis_result = await gpt_analyzer.analyze_image_with_vision(image_base64, PROFILE_SCREENSHOT_PROMPT)
        
        try: await bot_instance.delete_message(chat_id=processing_msg.chat.id, message_id=processing_msg.message_id)
        except TelegramAPIError: logger.warning("Не вдалося видалити повідомлення про обробку.")

        if analysis_result and "error" not in analysis_result:
            logger.info(f"Успішний аналіз профілю для {user_name}: {analysis_result}")
            response_parts = [f"<b>Аналіз твого профілю, {user_name}:</b>"]
            fields_translation = {
                "game_nickname": "🎮 Нікнейм", "mlbb_id_server": "🆔 ID (Сервер)",
                "current_rank": "🏆 Поточний ранг", "highest_rank_season": "🌟 Найвищий ранг (сезон)",
                "matches_played": "⚔️ Матчів зіграно", "likes_received": "👍 Лайків отримано",
                "location": "🌍 Локація", "squad_name": "🛡️ Сквад"
            }
            has_data = False
            for key, readable_name in fields_translation.items():
                value = analysis_result.get(key)
                if value is not None:
                    response_parts.append(f"<b>{readable_name}:</b> {html.escape(str(value))}")
                    has_data = True
                else:
                     response_parts.append(f"<b>{readable_name}:</b> <i>не розпізнано</i>")
            if not has_data and analysis_result.get("raw_response"):
                 response_parts.append(f"\n<i>Не вдалося структурувати дані. Можливо, на скріншоті недостатньо інформації або вона нечітка.</i>")
            elif not has_data:
                 response_parts.append(f"\n<i>Не вдалося розпізнати дані на скріншоті. Спробуй інший або переконайся, що він чіткий.</i>")
            await message.reply("\n".join(response_parts))
        else:
            error_msg = analysis_result.get('error', 'Невідома помилка аналізу.') if analysis_result else 'Відповідь від Vision API не отримана.'
            details = analysis_result.get('details', '') if analysis_result else ''
            logger.error(f"Помилка аналізу профілю для {user_name}: {error_msg} {details}")
            await message.reply(
                f"😔 Вибач, {user_name}, сталася помилка під час аналізу скріншота.\n"
                f"<i>Помилка: {html.escape(error_msg)}</i>"
            )
    except Exception as e:
        logger.exception(f"Критична помилка обробки скріншота профілю для {user_name}: {e}")
        try: await bot_instance.delete_message(chat_id=processing_msg.chat.id, message_id=processing_msg.message_id)
        except Exception: pass
        await message.reply(f"Дуже шкода, {user_name}, але сталася непередбачена помилка при обробці зображення. Спробуй ще раз пізніше.")
    finally:
        await state.clear()

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot, Command("cancel"))
async def cancel_profile_analysis(message: Message, state: FSMContext):
    logger.info(f"Користувач {message.from_user.first_name} скасував аналіз профілю командою /cancel.")
    await state.clear()
    await message.reply("Аналіз скріншота скасовано. Ти можеш продовжити використовувати команду /go.")

@dp.message(VisionAnalysisStates.awaiting_profile_screenshot)
async def handle_wrong_input_for_profile_screenshot(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "/cancel": # Додаткова обробка /cancel як тексту
        await cancel_profile_analysis(message, state)
        return
    if message.text and message.text.startswith("/go"):
        logger.info(f"Користувач {message.from_user.first_name} ввів /go у стані очікування скріншота. Скасовую стан і виконую /go.")
        await state.clear()
        await cmd_go(message, state)
    elif message.text:
        logger.info(f"Користувач {message.from_user.first_name} надіслав текст замість фото. Пропоную скасувати або надіслати фото.")
        await message.reply("Очікувався скріншот профілю. Будь ласка, надішли фото або використай /cancel для скасування аналізу.")
    else:
        await message.reply("Будь ласка, надішли саме фото (скріншот) свого профілю або команду /cancel для скасування.")

# === ГЛОБАЛЬНИЙ ОБРОБНИК ПОМИЛОК ===
@dp.errors()
async def error_handler(update_event, exception: Exception):
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
    logger.info(f"🚀 Запуск MLBB IUI mini v2.4... (PID: {os.getpid()})")
    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini v2.4 запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Промпт v2.3, Vision (профіль /analyzeprofile) активні!</b>\n"
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
        # Закриття сесії бота, якщо вона була створена і не закрита
        # Aiogram 3.x зазвичай сам керує сесією бота, але для ClientSession, створених вручну, потрібне явне закриття.
        # У нас MLBBChatGPT керує своєю сесією через __aexit__.
        # Сесія самого Bot (bot.session) закривається автоматично при зупинці polling або явно, якщо потрібно.
        if bot.session and hasattr(bot.session, "close") and not bot.session.closed: # type: ignore
             await bot.session.close() # type: ignore
             logger.info("Сесію HTTP клієнта екземпляра Bot закрито.")
        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    asyncio.run(main())
