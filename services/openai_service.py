import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import aiohttp
from aiohttp import ClientSession, ClientTimeout

# Припустимо, що logger та API_KEY будуть передані або імпортовані
# from config import OPENAI_API_KEY, logger
# Для цього прикладу, я тимчасово задам їх тут або очікую передачу в __init__
# logger = logging.getLogger(__name__)


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
1.  **Цифри та Зірки (★) в Рангах:** Дуже уважно розпізнавай УСІ цифри в показниках **Найвищого Рангу Сезону** (наприклад, 'Міфічна Слава 267 ★', 'Міфічний 1111 ★'). Не пропускай жодної цифри.
2.  **Найвищий Ранг Сезону:** Це ранг, іконка якого розташована біля підпису "Highest Rank". Часто він має показник зірок (★) або очок слави. Включай їх повністю.
3.  **Відсутність Даних:** Якщо будь-яка інформація (наприклад, локація, нікнейм, ID, найвищий ранг) дійсно відсутня на скріншоті або нерозбірлива, використовуй значення `null` для відповідного поля в JSON. Не вигадуй дані.
4.  **Точність ID та Сервера:** Уважно розпізнавай цифри ID та сервера. Якщо сервер не видно, вказуй тільки ID (наприклад, '123456789'). Якщо ID не видно, повертай `null`.

Будь максимально точним. Якщо якась інформація відсутня на скріншоті, використовуй значення null для відповідного поля.
Розпізнавай текст уважно, навіть якщо він невеликий або частково перекритий.
"""

PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — харизматичний та дотепний коментатор матчів Mobile Legends, який вміє знайти родзинку в кожному гравцеві. Твоя мета — створити короткий (2-5 речень), але яскравий та персоналізований "вау-ефект" опис для гравця {user_name}, базуючись на даних його профілю. Опис має бути схожим на коментар стрімера під час трансляції.

Ось дані з профілю:
- Нікнейм: {game_nickname}
- Найвищий ранг сезону: {highest_rank_season}
- Матчів зіграно: {matches_played}
- Лайків отримано: {likes_received}
- Локація: {location}
- Сквад: {squad_name}

ТВОЇ ЗАВДАННЯ ДЛЯ СТВОРЕННЯ УНІКАЛЬНОГО КОМЕНТАРЯ:
1.  **Знайди "фішку":** На чому можна зробити акцент? Це може бути:
    *   Вражаюча кількість матчів або лайків.
    *   Високий ранг (особливо якщо є зірки/очки слави).
    *   Цікавий або кумедний нікнейм (обіграй його!).
    *   Належність до скваду (можна пожартувати про командну синергію).
    *   Незвичайне поєднання даних (наприклад, мало матчів, але високий ранг).
    *   Навіть відсутність якихось даних можна обіграти з гумором (наприклад, "настільки крутий, що приховує свою локацію!").
2.  **Вибери стиль коментаря (можеш комбінувати):**
    *   **Захоплення:** "Ого, {game_nickname} просто розриває! {matches_played} матчів – це ж скільки каток затащено!"
    *   **Гумор/Іронія (дружня):** "Так-так, {game_nickname}, бачу, ти не тільки фармиш крипів, а й лайки! {likes_received} – це серйозна заявка на популярність!"
    *   **Повага:** "З таким профілем, як у {game_nickname} ({highest_rank_season}), жарти вбік. Справжній майстер своєї справи."
    *   **Інтрига:** "Цікаво, {game_nickname} з {location}, скільки ще рекордів ти плануєш побити?"
3.  **Використовуй ігровий сленг доречно:** "тащер", "імба", "фармить", "розносить катки", "в топі", "скіловий" тощо. Але не переборщи.
4.  **Уникай повторень:** Якщо попередні коментарі були про "тащера", спробуй інший підхід.
5.  **Будь лаконічним:** 2-5 речень максимум.
6.  **ТІЛЬКИ текст коментаря:** Без привітань типу "Привіт, {user_name}!" і без Markdown/HTML. Тільки чистий текст.

ПОГАНИЙ ПРИКЛАД (шаблонно): "{game_nickname} крутий, багато грає, високий ранг. Молодець!"
ДОБРИЙ ПРИКЛАД (креативно для гравця "НіндзяВтапках" з 100 матчів, ранг Епік):
"НіндзяВтапках, ти хоч і ніндзя, але твої 100 каток на Епіку вже не такі й тихі! Мабуть, тапки дійсно щасливі. Фармиш респект, так тримати!"

Зроби так, щоб кожен гравець відчув себе особливим!
"""

class MLBBChatGPT:
    """Клас для взаємодії з OpenAI API для генерації тексту та аналізу зображень."""
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        # Ініціалізуємо логер для цього класу
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")


    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=60), # Загальний таймаут для сесії
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
ВАЖЛИВО: Не вигадуй імена героїв або механіки. Якщо ти не впевнений на 100% в імені героя або деталі, краще зазнач це.
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
            best_emoji = "💡" # Default emoji
            # Check for more specific keys first
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета"]
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else: # If no specific key matched, try general keys
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
        
        # Балансування HTML тегів (b, i, code)
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
                # Removing extra closing tags is more complex and risky to do automatically.
                # For now, just log it. A more robust HTML parser/balancer might be needed for complex cases.
                self.class_logger.warning(f"Beautify: Виявлено {close_count - open_count} зайвих тегів {close_tag}.")

        self.class_logger.debug(f"Beautify: Текст після обробки (перші 100 символів): '{text[:100]}'")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str: # Для /go
        """Отримує відповідь від GPT на текстовий запит користувача."""
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name}': '{user_query}'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4.1", # Жорстко задана модель
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 1000, # Максимальна кількість токенів у відповіді
            "temperature": 0.65, # Креативність відповіді (0.0 - 1.0)
            "top_p": 0.9,       # Ядерна вибірка
            "presence_penalty": 0.3, # Штраф за повторення тем
            "frequency_penalty": 0.2  # Штраф за повторення слів/фраз
        }
        self.class_logger.debug(f"Параметри тексту для GPT: temperature={payload['temperature']}")
        try:
            if not self.session or self.session.closed:
                 self.class_logger.warning("Aiohttp сесія для текстового GPT була закрита або відсутня. Перестворюю.")
                 # Recreate session with its specific needs if it was closed
                 self.session = ClientSession(
                    timeout=ClientTimeout(total=45), # Таймаут для цього конкретного запиту
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
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": "gpt-4o-mini", # Жорстко задана модель
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", 
                         "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                        }
                    ]
                }
            ],
            "max_tokens": 1500,
            "temperature": 0.3 # Нижча температура для більш точного аналізу
        }
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")

        try:
            # Використання тимчасової сесії для Vision API, щоб уникнути конфліктів,
            # якщо основна сесія використовується для інших запитів або має інші налаштування.
            # Або переконайтеся, що self.session налаштований для обох типів запитів.
            # Для простоти, якщо self.session вже існує і підходить, можна його використовувати.
            # Але для ізоляції помилок та налаштувань, окрема сесія або перестворення може бути кращим.
            # Тут я використаю тимчасову сесію.
            async with ClientSession(headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session: # Передаємо тільки Authorization, Content-Type буде в post
                async with temp_session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers, # Content-Type важливий тут
                    json=payload,
                    timeout=ClientTimeout(total=90) # Більший таймаут для аналізу зображень
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
            except aiohttp.ContentTypeError: # Якщо відповідь не JSON
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
                # або містить текст до/після JSON об'єкта
                if not json_str.startswith("{") and "{" in json_str:
                    json_str = json_str[json_str.find("{"):]
                if not json_str.endswith("}") and "}" in json_str:
                    json_str = json_str[:json_str.rfind("}")+1]

                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    self.class_logger.error(f"Помилка декодування JSON з Vision API: {e}. Рядок: '{json_str[:300]}'")
                    # Повертаємо оригінальний content, щоб можна було побачити, що саме прийшло
                    return {"error": "Не вдалося розпарсити JSON відповідь від Vision API.", "raw_response": content}
            else:
                self.class_logger.error(f"Vision API відповідь без контенту: {result}")
                return {"error": "Vision API повернуло порожню відповідь."}
        else:
            error_text = await response.text()
            self.class_logger.error(f"Vision API помилка: {response.status} - {error_text[:300]}")
            return {"error": f"Помилка Vision API: {response.status}", "details": error_text[:200]} # Обмеження довжини деталей помилки

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        """Генерує дружній опис профілю на основі даних від Vision API."""
        self.class_logger.info(f"Запит на генерацію опису профілю для '{user_name}'.")

        # Екрануємо дані профілю перед вставкою в промпт, якщо вони будуть відображатися як є
        # Але оскільки вони використовуються в f-string, Python подбає про перетворення в рядок.
        # Важливо, щоб PROFILE_DESCRIPTION_PROMPT_TEMPLATE був захищений від ін'єкцій, якщо дані непередбачувані.
        # Для нашого випадку, дані приходять з Vision API, тому ризик менший, але обережність не завадить.
        escaped_profile_data = {
            k: html.escape(str(v)) if v is not None else "Не вказано" 
            for k, v in profile_data.items()
        }

        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(
            user_name=html.escape(user_name), # Екрануємо ім'я користувача
            game_nickname=escaped_profile_data.get("game_nickname", "Не вказано"),
            highest_rank_season=escaped_profile_data.get("highest_rank_season", "Не вказано"),
            matches_played=escaped_profile_data.get("matches_played", "N/A"),
            likes_received=escaped_profile_data.get("likes_received", "N/A"),
            location=escaped_profile_data.get("location", "Не вказано"),
            squad_name=escaped_profile_data.get("squad_name", "Немає"), # "Немає" якщо відсутній
        )
        payload = {
            "model": "gpt-4.1", # Жорстко задана модель
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 300,  # Достатньо для короткого опису
            "temperature": 0.7, # Трохи більше креативності для опису
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        self.class_logger.debug(f"Параметри для опису профілю: temp={payload['temperature']}, max_tokens={payload['max_tokens']}")

        try:
            if not self.session or self.session.closed:
                 self.class_logger.warning("Aiohttp сесія для опису профілю була закрита або відсутня. Перестворюю.")
                 self.session = ClientSession(
                    timeout=ClientTimeout(total=30), # Таймаут для цього запиту
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions", json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): {response.status} - {error_text}")
                    return "<i>Не вдалося згенерувати дружній опис.</i>" # Повертаємо HTML-безпечний текст
                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    self.class_logger.error(f"OpenAI API помилка (опис профілю): несподівана структура - {result}")
                    return "<i>Не вдалося отримати опис від ШІ.</i>"

                description_text = result["choices"][0]["message"]["content"].strip()
                self.class_logger.info(f"Згенеровано опис профілю: '{description_text[:100]}'")
                # Промпт вимагає "ТІЛЬКИ текст коментаря... Без Markdown/HTML."
                # Тому ми не повинні додатково екранувати HTML тут, якщо GPT дотримується інструкції.
                # Однак, оскільки цей текст буде вставлений в HTML повідомлення,
                # будь-які символи, що мають спеціальне значення в HTML (наприклад, <, >, &),
                # повинні бути екрановані на етапі формування фінального повідомлення.
                # Краще повертати чистий текст, а екрануванням займатися в хендлері.
                # Але для безпеки, якщо GPT раптом додасть HTML, краще його екранувати.
                # Враховуючи інструкцію "без HTML", припустимо, що текст чистий.
                return description_text 
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис профілю) для: '{user_name}'")
            return "<i>Опис профілю генерувався занадто довго...</i>"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис профілю) для '{user_name}': {e}")
            return "<i>Виникла помилка при генерації опису.</i>"
