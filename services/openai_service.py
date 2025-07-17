#services/openai_service.py
import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import aiohttp
from aiohttp import ClientSession, ClientTimeout

# 💎 НОВІ ІМПОРТИ ДЛЯ ДИНАМІЧНОЇ СИСТЕМИ
from services.context_engine import gather_context
from services.prompt_director import prompt_director


# === ФІЛЬТР НЕБАЖАНИХ ФРАЗ ===
BANNED_PHRASES = [
    "ульта фані в кущі",
    "це тобі не лайн фармить",
    "як франко хук кидати",
    "мов алдос ультою",
    # Можна додати інші фрази, які стали заїждженими
]

def _filter_cringy_phrases(response: str) -> str:
    """Видаляє або замінює заїжджені фрази з відповіді."""
    original_response = response
    for phrase in BANNED_PHRASES:
        if phrase in response.lower():
            # Проста стратегія: видаляємо речення, що містить фразу
            sentences = re.split(r'(?<=[.!?])\s+', response)
            filtered_sentences = [s for s in sentences if phrase not in s.lower()]
            response = ' '.join(filtered_sentences)
            logging.info(f"Відфільтровано фразу '{phrase}' з відповіді.")
    # Якщо після фільтрації нічого не залишилось, повертаємо оригінал
    return response if response.strip() else original_response

# === ШАБЛОНИ ДЛЯ ГЕНЕРАЦІЇ ОПИСІВ (залишаються, оскільки це специфічні завдання) ===

LEGEND_PROMPT_TEMPLATE = """
Ти — GGenius, легендарний оповідач та AI-дизайнер. Твоє завдання — створити епічну, але структуровану та візуально привабливу легенду про гравця.

**ДАНІ ДЛЯ ЛЕГЕНДИ:**
- **Гравець:** {user_name}
- **Нікнейм:** {game_nickname}
- **ID (Сервер):** {mlbb_id_server}
- **Найвищий Ранг:** {highest_rank_season}
- **Кількість Матчів:** {matches_played}
- **Кількість Лайків:** {likes_received}
- **Локація:** {location}
- **Сквад:** {squad_name}

**КРИТИЧНІ ВИМОГИ ДО ФОРМАТУ:**
1.  **ЗАГОЛОВОК:** Почни відповідь із заголовка, використовуючи `<b>` та відповідний емодзі. Приклад: `🏆 <b>Легенда про {game_nickname}</b>`
2.  **РОЗПОВІДЬ (1-2 абзаци):** Створи епічну розповідь, органічно вплітаючи в неї **локацію, сквад та ID**.
3.  **КЛЮЧОВІ ДОСЯГНЕННЯ (Список):** Після розповіді додай чіткий, але короткий список з 2-3 найважливіших досягнень.
    - Використовуй `•` для пунктів списку.
    - **ОБОВ'ЯЗКОВО** виділяй цифри та назви рангів тегом `<b>`.
    - Приклад: `• <b>{matches_played}</b> разів ти виходив на поле бою!`
4.  **ЗАВЕРШЕННЯ:** Закінчи відповідь надихаючою фразою або порадою в `<i>`.

**ЗАБОРОНЕНО:**
- Створювати суцільний текст без форматування.
- Перелічувати всі дані у вигляді "ключ: значення".

Створи шедевр, гідний цього воїна!
"""

PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — GGenius, AI-аналітик MLBB. Напиши короткий (3-5 речень) коментар про статистику гравця {user_name}.
Дані ({stats_filter_type}):
- Матчі: {matches_played}, Перемоги: {win_rate}%, MVP: {mvp_count} ({mvp_rate_percent}%)
- KDA: {kda_ratio}, Участь у боях: {teamfight_participation_rate}%
- Золото/хв: {avg_gold_per_min}
- Легендарні: {legendary_count}, Дикунства: {savage_count} (частота: {savage_frequency}/1000), Маніяки: {maniac_count}
- Серія перемог: {longest_win_streak}, Макс. вбивств: {most_kills_in_one_game}
- Ефективність золота (шкода/золото): {damage_per_gold_ratio}
- Частка MVP у перемогах: {mvp_win_share_percent}%
- Всього перемог: {total_wins}

ЗАВДАННЯ:
1.  **Аналіз GGenius:** Акцент на високих показниках (Win Rate, KDA, MVP Рейтинг), кількості матчів/перемог, Savage (особливо).
2.  **Стиль:** Позитивний, підбадьорливий, з доречним ігровим сленгом.
3.  **ТІЛЬКИ ТЕКСТ:** Без Markdown/HTML.

Приклад:
"Ого, {user_name}, твої {matches_played} матчів у '{stats_filter_type}' вражають! Мати {mvp_rate_percent}% MVP-рейт – це сильно! А ефективність з[...]

Підкресли унікальність гравця!
"""

UNIVERSAL_VISION_PROMPT_TEMPLATE = """
Ти — GGenius, AI-геймер та аналітик MLBB спільноти. 

🎯 ЗАВДАННЯ: Проаналізуй зображення та дай коротку (1-3 речення), релевантну відповідь як учасник чату.

КОНТЕКСТ КОРИСТУВАЧА:
- Ім'я: {user_name}
- Це Telegram-чат MLBB спільноти
- Очікується природна, дружня реакція
{caption_context}

🔍 ЩО РОБИТИ:
1. **Визнач тип контенту**: мем, скріншот гри, текст, профіль гравця, статистика, ігровий процес тощо
2. **Дай підходящу реакцію**: 
   - Мем → посміхнись, прокоментуй гумор
   - Скріншот MLBB → проаналізуй/похвали/дай пораду
   - Текст → переклади/поясни якщо потрібно
   - Профіль/стати → короткий аналіз
   - Інше → дружній коментар

🎨 СТИЛЬ:
- Коротко, по суті, з особистістю
- Використовуй відповідні емодзі (1-2 максимум)
- Ігровий сленг приветствується
- Звертайся до {user_name} за іменем
- НЕ питай "що це?" - сам роби висновки

❌ ЗАБОРОНЕНО:
- Довгі пояснення (це чат, не лекція)
- Формальний тон
- Просити уточнення
- Markdown форматування

Дай живу, людську реакцію як справжній член MLBB-спільноти!
"""

WEB_SEARCH_PROMPT_TEMPLATE = """
Ти — GGenius, твій персональний AI-наставник та стратегічний аналітик у світі Mobile Legends. Ти "свій пацан", який завжди на вайбі.

**Твоя місія:**
Надати коротку, але вичерпну відповідь на запит користувача, використовуючи найсвіжішу інформацію з Інтернету.

**Контекст:**
- Користувач: '{user_name}'
- Запит: "{user_query}"

**КРИТИЧНІ ІНСТРУКЦІЇ:**
1.  **СТИЛЬ GGENIUS:** Говори як досвідчений геймер — впевнено, з гумором, використовуючи ігровий сленг ("катка", "імба", "нерф", "мета"). Додавай доречні емодзі (🔥, 🧠, 🏆, 💡).
2.  **МАКСИМАЛЬНА ДОВЖИНА:** Твоя відповідь має бути дуже стислою, приблизно **1000 символів**. Фокусуйся на найголовнішому. Не пиши довгих полотен тексту.
3.  **БЕЗ ДЖЕРЕЛ:** **НЕ** додавай посилання або список джерел у свою відповідь. Просто дай інформацію. Виняток: якщо користувач прямо попросив посилання.
4.  **ФОРМАТУВАННЯ:** Використовуй HTML-теги для структурування: `<b>` для акцентів, `<i>` для порад, `<code>` для назв.
5.  **МОВА:** Відповідай українською.

Давай, видай базу по запиту! 🔥
"""


class MLBBChatGPT:
    TEXT_MODEL = "gpt-4.1" 
    VISION_MODEL = "gpt-4.1"
    SEARCH_MODEL = "gpt-4o-mini-search-preview"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: ClientSession | None = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.class_logger.info(f"GGenius Service (MLBBChatGPT) ініціалізовано. Текстова модель: {self.TEXT_MODEL}, Vision модель: {self.VISION_MODEL}, Пошукова модель: {self.SEARCH_MODEL}")

    async def __aenter__(self) -> "MLBBChatGPT":
        self.session = ClientSession(
            timeout=ClientTimeout(total=90), 
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("Aiohttp сесію створено та відкрито.")
        return self

    async def __aexit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any | None) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("Aiohttp сесію закрито.")
        if exc_type:
            self.class_logger.error(f"Помилка в GGenius Service (MLBBChatGPT) під час виходу з контексту: {exc_type} {exc_val}", exc_info=True)

    def _beautify_response(self, text: str) -> str:
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
        
        # --- Markdown to HTML Conversion ---
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
        text = re.sub(r'(?<!\*)\*(?!\s|\*)(.+?)(?<!\s|\*)\*(?!\*)', r'<i>\1</i>', text)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        
        # --- ❗️ NEW: HTML Sanitization ---
        # Спочатку замінюємо теги, що мають означати розрив рядка, на \n
        sanitized_text = re.sub(r'</(li|p|div|ul|ol)>', '\n', text, flags=re.IGNORECASE)
        # Потім видаляємо всі інші непідтримувані теги
        sanitized_text = re.sub(r'<(/?)(ul|ol|li|p|div|span)\b[^>]*>', '', sanitized_text, flags=re.IGNORECASE)

        if text != sanitized_text:
            self.class_logger.warning(f"Beautify: Очищено непідтримувані HTML теги. Оригінал: '{text[:100]}...', Результат: '{sanitized_text[:100]}...'")
            text = sanitized_text

        # --- Formatting and Structuring ---
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍", "комунікація": "💬",
            "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄", "командна гра": "🤝",
            "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", "стратегі": "🎯", "мета": "🔥",
            "поточна мета": "📊", "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "🔑", "предмет": "💎", "збірка": "🛠️",
            "аналіз": "📊", "статистика": "📈", "оновлення": "⚙️", "баланс": "⚖️", "скріншот": "📸",
            "унікальність": "🌟", "можливості": "🚀", "фішка": "🎯", "прикол": "😂", "інсайт": "💡",
            "висновок": "🏁", "запитання": "❓", "відповідь": "💬", "порада": "💡"
        }

        def replace_header(match: re.Match) -> str:
            header_text_raw = match.group(1).strip(": ")
            header_text = header_text_raw.capitalize() 
            best_emoji = "💡" 
            priority_keys = ["скріншот", "унікальність", "можливості", "фішка", "прикол", "інсайт", "висновок", "запитання", "відповідь", "порада"]
            
            found_specific = False
            for key in priority_keys:
                if key in header_text_raw.lower(): 
                    best_emoji = header_emojis.get(key, best_emoji)
                    found_specific = True
                    break
            if not found_specific:
                for key_general, emj in header_emojis.items():
                    if key_general in header_text_raw.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>" 

        text = re.sub(r"^(?:#|\#{2}|\#{3})\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE) 
        text = re.sub(r"^\s*•\s+[\-\*]\s+", "  ◦ ", text, flags=re.MULTILINE) 
        text = re.sub(r"\n{3,}", "\n\n", text) 
        
        tags_to_balance = ["b", "i", "code"]
        for tag in tags_to_balance:
            open_tag_pattern = re.compile(re.escape(f"<{tag}>"))
            close_tag_pattern = re.compile(re.escape(f"</{tag}>"))
            open_tags = [m.start() for m in open_tag_pattern.finditer(text)]
            close_tags = [m.start() for m in close_tag_pattern.finditer(text)]
            open_count = len(open_tags)
            close_count = len(close_tags)

            if open_count > close_count:
                missing_tags_count = open_count - close_count
                text += f"</{tag}>" * missing_tags_count
                self.class_logger.warning(f"Beautify: Додано {missing_tags_count} незакритих тегів '</{tag}>' в кінці тексту.")
            elif close_count > open_count:
                 self.class_logger.warning(f"Beautify: Виявлено {close_count - open_count} зайвих закриваючих тегів '</{tag}>'. Залишено без змін.")
        self.class_logger.debug(f"Beautify: Текст після обробки (перші 100 символів): '{text[:100]}'")
        return text.strip()

    async def _execute_openai_request(self, session: ClientSession, payload: dict[str, Any], user_name_for_error_msg: str) -> str:
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
            ) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка: {response.status} - {error_details}")
                    return f"Вибач, {user_name_for_error_msg}, проблема з доступом до AI-мозку GGenius 😔 (код: {response.status}). Спробуй ще раз трохи згодом."

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка: несподівана структура або порожній контент - {response_data}")
                    return f"Отакої, {user_name_for_error_msg}, GGenius щось не те видав або взагалі мовчить 🤯. Спробуй перефразувати запит."
                
                self.class_logger.info(f"Сира відповідь від GGenius (перші 100): '{content[:100]}'")
                if payload.get("model") == self.TEXT_MODEL and "Контекст:" in payload["messages"][0].get("content", ""):
                    content = _filter_cringy_phrases(content)
                
                return self._beautify_response(content)

        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"OpenAI API помилка з'єднання: {e}", exc_info=True)
            return f"Блін, {user_name_for_error_msg}, не можу достукатися до серверів GGenius 🌐. Схоже, інтернет вирішив взяти вихідний."
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout для запиту.")
            return f"Ай-ай-ай, {user_name_for_error_msg}, GGenius задумався так сильно, що аж час вийшов ⏳. Може, спробуєш ще раз, тільки простіше?"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка GGenius: {e}")
            return f"Щось пішло не так, {user_name_for_error_msg} 😕. Вже розбираюся, в чому прикол. А поки спробуй ще раз!"

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Застарілий метод для простих запитів.
        У майбутньому буде замінено на generate_conversational_reply.
        """
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит до GGenius (/go) від '{user_name_escaped}': '{user_query[:100]}...'")
        
        # Створюємо простий системний промпт для сумісності
        system_prompt = (
            "Ти — GGenius, твій персональний AI-наставник та стратегічний аналітик у світі Mobile Legends. "
            "Говори як досвідчений геймер — впевнено, з гумором, іноді з легкою іронією. "
            "Використовуй HTML: <b> для акцентів, <i> для порад, <code> для ID або назв."
        )

        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html.escape(user_query)}
            ],
            "max_tokens": 2000, "temperature": 0.7, "top_p": 0.9,
            "presence_penalty": 0.3, "frequency_penalty": 0.2  
        }
        self.class_logger.debug(f"Параметри для GGenius (/go): {payload['model']=}, {payload['temperature']=}")
        
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для GGenius (/go) була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=120), headers={"Authorization": f"Bearer {self.api_key}"}) 
            temp_session_created = True
        try:
            return await self._execute_openai_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для GGenius (/go) закрито.")

    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> dict[str, Any] | None:
        response_text = await response.text()
        try:
            if response.status != 200:
                self.class_logger.error(f"Vision API HTTP помилка: {response.status} - {response_text[:300]}")
                try:
                    error_data = json.loads(response_text)
                    error_message = error_data.get("error", {}).get("message", response_text)
                except json.JSONDecodeError:
                    error_message = response_text
                return {"error": f"Помилка Vision API: {response.status}", "details": error_message[:200]}
            result = json.loads(response_text)
        except json.JSONDecodeError:
            self.class_logger.error(f"Vision API відповідь не є валідним JSON. Статус: {response.status}. Відповідь: {response_text[:300]}")
            return {"error": "Vision API повернуло не JSON відповідь.", "raw_response": response_text}

        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            self.class_logger.error(f"Vision API відповідь без контенту: {result}")
            return {"error": "Vision API повернуло порожню відповідь."}

        self.class_logger.info(f"Vision API сира відповідь отримана (перші 150 символів): {content[:150].replace('\n', ' ')}")
        json_str = content.strip()
        match = re.search(r"```json\s*(\{.*?\})\s*```", json_str, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            start_brace = json_str.find("{")
            end_brace = json_str.rfind("}")
            if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
                json_str = json_str[start_brace : end_brace + 1]
            else:
                self.class_logger.error(f"Не вдалося знайти валідний JSON блок у відповіді Vision API. Контент: '{content[:300]}'")
                return {"error": "Не вдалося вилучити JSON з відповіді Vision API.", "raw_response": content}
        try:
            parsed_json = json.loads(json_str)
            self.class_logger.info(f"Vision API JSON успішно розпарсено.")
            return parsed_json
        except json.JSONDecodeError as e:
            self.class_logger.error(f"Помилка декодування JSON з Vision API: {e}. Рядок для парсингу: '{json_str[:300]}'")
            return {"error": "Не вдалося розпарсити JSON відповідь від Vision API (помилка декодування).", "raw_response": content}

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> dict[str, Any] | None:
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70].replace('\n', ' ')}...'")
        payload = {
            "model": self.VISION_MODEL,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}
            ],
            "max_tokens": 2500, "temperature": 0.15 
        }
        self.class_logger.debug(f"Параметри для Vision API: {payload['model']=}, {payload['max_tokens']=}, {payload['temperature']=}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Vision API була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            async with current_session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                return await self._handle_vision_response(response)
        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"Vision API помилка з'єднання: {e}", exc_info=True)
            return {"error": "Помилка з'єднання з Vision API.", "details": str(e)}
        except asyncio.TimeoutError:
            self.class_logger.error("Vision API Timeout помилка.")
            return {"error": "Запит до Vision API зайняв занадто багато часу."}
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка під час виклику Vision API: {e}")
            return {"error": f"Загальна помилка при аналізі зображення: {str(e)}"}
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для Vision API закрито.")

    async def _execute_description_request(self, session: ClientSession, payload: dict[str, Any], user_name_for_error_msg: str) -> str:
        try:
            async with session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка (опис): {response.status} - {error_details}")
                    return f"<i>Упс, {user_name_for_error_msg}, GGenius не зміг згенерувати опис (код: {response.status}). Трабли...</i>" 

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка (опис): порожній контент - {response_data}")
                    return f"<i>Ой, {user_name_for_error_msg}, GGenius щось не захотів генерувати опис. Пусто...</i>" 
                
                self.class_logger.info(f"Згенеровано опис (перші 100): '{content[:100]}'")
                if "Контекст:" in payload["messages"][0].get("content", ""):
                     content = _filter_cringy_phrases(content)
                return content.strip()
        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"OpenAI API помилка з'єднання (опис): {e}", exc_info=True)
            return f"<i>Ех, {user_name_for_error_msg}, не можу підключитися до AI для опису. Інтернет барахлить?</i>" 
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис) для: '{user_name_for_error_msg}'")
            return f"<i>{user_name_for_error_msg}, GGenius так довго думав над описом, що аж час вийшов...</i>" 
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис) для '{user_name_for_error_msg}': {e}")
            return f"<i>При генерації опису для {user_name_for_error_msg} щось пішло шкереберть. Буває...</i>" 

    async def get_profile_legend(self, user_name: str, profile_data: dict[str, Any]) -> str:
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на генерацію 'Легенди' профілю для '{user_name_escaped}'.")
        
        escaped_profile_data = {k: html.escape(str(v)) if v is not None else "Не вказано" for k, v in profile_data.items()}
        
        template_payload = {
            "user_name": user_name_escaped,
            "game_nickname": escaped_profile_data.get("game_nickname", "Невідомий воїн"),
            "mlbb_id_server": escaped_profile_data.get("mlbb_id_server", "ID приховано"),
            "highest_rank_season": escaped_profile_data.get("highest_rank_season", "Ранг невідомий"),
            "matches_played": escaped_profile_data.get("matches_played", "незліченну кількість"),
            "likes_received": escaped_profile_data.get("likes_received", "безліч"),
            "location": escaped_profile_data.get("location", "невідомих земель"),
            "squad_name": escaped_profile_data.get("squad_name", "самотній вовк"),
        }
        
        try:
            system_prompt_text = LEGEND_PROMPT_TEMPLATE.format(**template_payload)
        except KeyError as e:
            self.class_logger.error(f"Помилка форматування LEGEND_PROMPT_TEMPLATE: відсутній ключ {e}. Дані: {template_payload}")
            return f"<i>Помилка підготовки даних для Легенди про {user_name_escaped}. Ключ: {e}</i>"

        payload = {
            "model": self.TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 450, "temperature": 0.8, "top_p": 0.9,
            "presence_penalty": 0.2, "frequency_penalty": 0.2
        }
        self.class_logger.debug(f"Параметри для Легенди профілю: {payload['model']=}, {payload['temperature']=}, {payload['max_tokens']=}")
        
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Легенди профілю була закрита. Створюю тимчасову.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            return await self._execute_description_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для Легенди профілю закрито.")

    async def get_player_stats_description(self, user_name: str, stats_data: dict[str, Any]) -> str:
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на генерацію опису статистики для '{user_name_escaped}' (з унікальними даними).")
        main_ind = stats_data.get("main_indicators", {})
        details_p = stats_data.get("details_panel", {})
        ach_left = stats_data.get("achievements_left_column", {})
        ach_right = stats_data.get("achievements_right_column", {})
        derived_s = stats_data.get("derived_stats", {})

        def get_value(data_dict: dict[str, Any] | None, key: str, default_val: Any = "N/A", precision: int | None = None) -> str:
            if data_dict is None: return str(default_val)
            val = data_dict.get(key)
            if val is None: return str(default_val)
            if isinstance(val, (int, float)) and precision is not None:
                try: return f"{float(val):.{precision}f}"
                except (ValueError, TypeError): return html.escape(str(val))
            return html.escape(str(val))

        template_data = {
            "user_name": user_name_escaped, "stats_filter_type": get_value(stats_data, 'stats_filter_type'),
            "matches_played": get_value(main_ind, 'matches_played'), "win_rate": get_value(main_ind, 'win_rate'),
            "mvp_count": get_value(main_ind, 'mvp_count'), "kda_ratio": get_value(details_p, 'kda_ratio', precision=2),
            "teamfight_participation_rate": get_value(details_p, 'teamfight_participation_rate'),
            "avg_gold_per_min": get_value(details_p, 'avg_gold_per_min'), "legendary_count": get_value(ach_left, 'legendary_count'),
            "savage_count": get_value(ach_right, 'savage_count'), "maniac_count": get_value(ach_left, 'maniac_count'),
            "longest_win_streak": get_value(ach_left, 'longest_win_streak'), "most_kills_in_one_game": get_value(ach_left, 'most_kills_in_one_game'),
            "total_wins": get_value(derived_s, 'total_wins', default_val="не розраховано"),
            "mvp_rate_percent": get_value(derived_s, 'mvp_rate_percent', default_val="N/A", precision=2),
            "savage_frequency": get_value(derived_s, 'savage_frequency_per_1000_matches', default_val="N/A", precision=2),
            "damage_per_gold_ratio": get_value(derived_s, 'damage_per_gold_ratio', default_val="N/A", precision=2),
            "mvp_win_share_percent": get_value(derived_s, 'mvp_win_share_percent', default_val="N/A", precision=2),
        }
        try:
            system_prompt_text = PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.format(**template_data) 
        except KeyError as e:
            self.class_logger.error(f"Помилка форматування PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE: відсутній ключ {e}. Дані: {template_data}")
            return f"<i>Помилка підготовки даних для опису статистики ({user_name_escaped}). Ключ: {e}</i>"

        payload = {
            "model": self.TEXT_MODEL, "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 250, "temperature": 0.73, "top_p": 0.9,
            "presence_penalty": 0.15, "frequency_penalty": 0.15
        }
        self.class_logger.debug(f"Параметри для опису статистики (з derived): {payload['model']=}, {payload['temperature']=}, {payload['max_tokens']=}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для опису статистики була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            return await self._execute_description_request(current_session, payload, user_name_escaped) 
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для опису статистики закрито.")
    
    # 💎 ОНОВЛЕНИЙ МЕТОД ГЕНЕРАЦІЇ РОЗМОВНОЇ ВІДПОВІДІ
    async def generate_conversational_reply(
        self,
        user_id: int,
        chat_history: list[dict[str, str]]
    ) -> str:
        """
        Генерує розмовну відповідь, використовуючи нову динамічну систему промптів.
        """
        self.class_logger.info(f"Запит на розмовну відповідь для user_id '{user_id}' через нову систему.")

        # 1. Збираємо повний вектор контексту
        context_vector = await gather_context(user_id, chat_history)

        # 2. Будуємо динамічний системний промпт
        system_prompt = prompt_director.build_prompt(context_vector)
        
        # 3. Готуємо повідомлення для API
        messages = [{"role": "system", "content": system_prompt}] + chat_history
        
        user_name_for_error_msg = "друже"
        if context_vector.user_profile and context_vector.user_profile.get("nickname"):
            user_name_for_error_msg = html.escape(context_vector.user_profile["nickname"])

        # 💎 ОНОВЛЕНА ЛОГІКА: Динамічні параметри для кращої адаптації
        intent = context_vector.last_message_intent
        temperature = {"technical_help": 0.4, "emotional_support": 0.75, "celebration": 0.8, "casual_chat": 0.9, "neutral": 0.7, "ambiguous_request": 0.6}.get(intent, 0.7)
        
        # ❗️ Радикально зменшуємо max_tokens для коротких відповідей
        if intent in ["emotional_support", "celebration", "casual_chat", "ambiguous_request"]:
            max_tokens = 60  # Жорсткий ліміт для 1-2 речень
        elif intent == "technical_help":
            max_tokens = 400 # Дозволяємо більше для технічних пояснень
        else:
            max_tokens = 150 # Для нейтральних/інших запитів

        payload = {
            "model": self.TEXT_MODEL, 
            "messages": messages, 
            "max_tokens": max_tokens, 
            "temperature": temperature,
            "top_p": 1.0, 
            "presence_penalty": 0.4, 
            "frequency_penalty": 0.5
        }
        self.class_logger.debug(f"Параметри для розмовної відповіді (intent: {intent}): {temperature=}, {max_tokens=}")
        
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для розмовної відповіді була закрита. Створюю тимчасову.")
            current_session = ClientSession(timeout=ClientTimeout(total=60), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            return await self._execute_description_request(current_session, payload, user_name_for_error_msg)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для розмовної відповіді закрито.")

    async def analyze_image_universal(
        self, 
        image_base64: str, 
        user_name: str,
        caption_text: str = ""
    ) -> str | None:
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на універсальний аналіз зображення від '{user_name_escaped}'.")
        
        caption_context = ""
        if caption_text and caption_text.strip():
            caption_context = f"\n- Підпис до зображення: '{html.escape(caption_text)}'"
            self.class_logger.debug(f"Додано контекст caption: {caption_context}")
        
        system_prompt = UNIVERSAL_VISION_PROMPT_TEMPLATE.format(
            user_name=user_name_escaped,
            caption_context=caption_context
        )
        
        payload = {
            "model": self.VISION_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": system_prompt}, 
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "low"}}
            ]}],
            "max_tokens": 150, "temperature": 0.8, "top_p": 0.9,
            "presence_penalty": 0.1, "frequency_penalty": 0.1
        }
        self.class_logger.debug(f"Параметри для універсального Vision: {payload['model']=}, {payload['max_tokens']=}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для універсального Vision була закрита. Створюю тимчасову.")
            current_session = ClientSession(timeout=ClientTimeout(total=60), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            async with current_session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"Universal Vision API HTTP помилка: {response.status} - {error_details}")
                    return None
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"Universal Vision API повернув порожню відповідь: {response_data}")
                    return None
                clean_response = content.strip()
                clean_response = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean_response)
                clean_response = re.sub(r'\*([^*]+)\*', r'\1', clean_response)
                self.class_logger.info(f"Універсальний Vision аналіз завершено для '{user_name_escaped}'. Довжина: {len(clean_response)}")
                return clean_response
        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"Universal Vision API помилка з'єднання: {e}", exc_info=True)
            return None
        except asyncio.TimeoutError:
            self.class_logger.error("Universal Vision API timeout помилка.")
            return None
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка Universal Vision для '{user_name_escaped}': {e}")
            return None
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для Universal Vision закрито.")

    def _detect_content_type_from_response(self, response: str) -> str:
        response_lower = response.lower()
        if any(word in response_lower for word in ["мем", "смішн", "жарт", "прикол", "кек", "лол"]): return "meme"
        elif any(word in response_lower for word in ["скріншот", "гра", "матч", "катка"]): return "screenshot"
        elif any(word in response_lower for word in ["текст", "напис", "переклад"]): return "text"
        elif any(word in response_lower for word in ["профіль", "акаунт", "гравець"]): return "profile"
        elif any(word in response_lower for word in ["статистика", "стати", "рейтинг"]): return "stats"
        elif any(word in response_lower for word in ["герой", "персонаж", "чемпіон"]): return "hero"
        elif any(word in response_lower for word in ["предмет", "айтем", "збірка"]): return "items"
        elif any(word in response_lower for word in ["турнір", "змагання", "чемпіонат"]): return "tournament"
        else: return "general"

    async def analyze_user_profile(self, image_base64: str, prompt: str) -> dict:
        """
        Аналізує скріншот профілю, статистики або героїв гравця та повертає структуровані дані.
        """
        self.class_logger.info(f"Запит на аналіз профілю з переданим промптом.")
        
        payload = {
            "model": self.VISION_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Ти - AI-аналітик MLBB. Витягни дані зі скріншота у форматі JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            "max_tokens": 1500,
            "temperature": 0.0,
        }

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning(f"Aiohttp сесія для analyze_user_profile була закрита. Створюю тимчасову.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True

        try:
            async with current_session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                if response.status != 200:
                    response_text = await response.text()
                    self.class_logger.error(f"Помилка OpenAI API при аналізі профілю: {response.status} - {response_text}")
                    return {"error": "Помилка відповіді від сервісу аналізу."}
                
                response_data = await response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API повернув порожній контент: {response_data}")
                    return {"error": "Сервіс аналізу повернув порожню відповідь."}

                return json.loads(content)

        except json.JSONDecodeError as e:
            self.class_logger.error(f"Помилка декодування JSON з OpenAI: {e}")
            return {"error": "Не вдалося обробити відповідь від AI. Спробуйте ще раз."}
        except Exception as e:
            self.class_logger.exception(f"Критична помилка під час аналізу профілю в OpenAI:")
            return {"error": f"Внутрішня помилка сервісу: {e}"}
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug(f"Тимчасову сесію для analyze_user_profile закрито.")

    async def get_web_search_response(self, user_name: str, user_query: str) -> str:
        """
        Виконує запит до спеціалізованої пошукової моделі OpenAI та форматує відповідь з цитатами.
        """
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит до Web Search (/search) від '{user_name_escaped}': '{user_query[:100]}...'")

        prompt = WEB_SEARCH_PROMPT_TEMPLATE.format(user_name=user_name_escaped, user_query=html.escape(user_query))
        
        payload = {
            "model": self.SEARCH_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500, 
        }
        self.class_logger.debug(f"Параметри для Web Search: {payload['model']=}, {payload['max_tokens']=}")

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Web Search була закрита. Створюю тимчасову.")
            current_session = ClientSession(timeout=ClientTimeout(total=120), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        
        try:
            async with current_session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"Web Search API HTTP помилка: {response.status} - {error_details}")
                    return f"Вибач, {user_name_escaped}, сервіс пошуку тимчасово недоступний (код: {response.status})."

                choice = response_data.get("choices", [{}])[0]
                message_content = choice.get("message", {}).get("content")

                if not message_content:
                    self.class_logger.warning(f"Web Search API повернув порожню відповідь для запиту: '{user_query}'")
                    return f"На жаль, {user_name_escaped}, не вдалося знайти інформацію за твоїм запитом."

                annotations = choice.get("message", {}).get("tool_calls", [{}])[0].get("function",{}).get("arguments",{}).get("citations", [])
                
                clean_text = re.sub(r'【\d+†source】', '', message_content).strip()
                
                sources_list_str = ""
                if annotations and any(word in user_query.lower() for word in ["посилання", "сайт", "ресурс", "source", "link"]):
                    unique_sources = {}
                    for anno in annotations:
                        url = anno.get('url')
                        if url and url not in unique_sources:
                             unique_sources[url] = anno.get('title', url.split('/')[2])

                    if unique_sources:
                        sources_list = []
                        for i, (url, title) in enumerate(unique_sources.items(), 1):
                            sources_list.append(f"{i}. <a href='{html.escape(url)}'>{html.escape(title)}</a>")
                        
                        sources_list_str = "\n\n<b>Джерела:</b>\n" + "\n".join(sources_list)

                final_response = clean_text + sources_list_str
                return self._beautify_response(final_response)

        except Exception as e:
            self.class_logger.exception(f"Критична помилка в get_web_search_response для {user_name_escaped}: {e}")
            return f"Щось пішло не так під час пошуку, {user_name_escaped}. Спробуй пізніше."
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для Web Search закрито.")