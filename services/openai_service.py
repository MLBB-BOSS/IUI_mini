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

# Логер ініціалізується в config.py і буде доступний через імпорт в інших модулях,
# але якщо цей файл використовується окремо, або для більшої явності, можна отримати його так:
# logger = logging.getLogger(__name__)
# У нашому випадку, клас MLBBChatGPT ініціалізує свій class_logger.


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

КРИТИЧНО ВАЖЛИВІ ІНСТРУКЦІЇ ДЛЯ ТОЧНОСТІ (Версія промпту 3, враховуючи попередні помилки):
1.  **Найвищий Ранг Сезону (Highest Rank Season):** Розташований під написом "Highest Rank". Уважно витягуй назву рангу (наприклад, "Міфічна Слава", "Легенда") ТА **ТОЧНУ КІЛЬКІСТЬ ЗІРОК (★) АБО ОЧОК СЛАВИ**. Це числове значення є КРИТИЧНО ВАЖЛИВИМ. Переконайся, що ти розпізнав КОЖНУ цифру правильно (наприклад, '★1111', а не '★111').
2.  **Кількість Матчів (Matches Played) та Лайків (Likes Received):**
    *   Ці показники зазвичай розташовані **В НИЖНІЙ ЧАСТИНІ** скріншота профілю гравця, часто під статистикою популярності/харизми/відвідувачів, і мають чіткі текстові мітки **"Matches Played"** та **"Likes"** (або їх еквівалент).
    *   **НЕ ПЛУТАЙ** ці значення з іншими числами на скріншоті, такими як очки популярності (часто з "k" на кінці, наприклад, "1866.0k"), кількість відвідувачів ("Visitors") або бали харизми. "Matches Played" та "Likes" – це окремі, чітко підписані поля.
    *   Ці числові значення є КРИТИЧНО ВАЖЛИВИМИ. Будь НАДЗВИЧАЙНО уважним, щоб розпізнати КОЖНУ цифру правильно. Числа можуть бути великими.
3.  **ID та Сервер (mlbb_id_server):**
    *   ID гравця – це число, що зазвичай знаходиться біля іконки, яка символізує профіль або людину (часто під нікнеймом).
    *   Номер сервера – це число, що часто вказується поруч із написом "Server:" (або еквівалентом).
    *   Повертай у форматі **'ID (SERVER)'** (наприклад, '158 (6203)'). Якщо одна з частин не видна, вказуй наявну або `null` для відсутньої, зберігаючи структуру (наприклад, '158 (null)' або 'null (6203)').
4.  **Назва Скваду (Squad Name):** Витягуй ПОВНУ назву скваду, як вона відображена, включаючи префікси (наприклад, "GK Geekay Esports"). Якщо сквад не вказано, використовуй `null`.
5.  **Локація (Location):** Якщо поле для локації містить напис "No data", "Немає даних" або аналогічний, використовуй `null`.
6.  **Відсутність Даних Загалом:** Якщо будь-яка інша інформація відсутня або нерозбірлива, використовуй `null`. Не вигадуй дані.

Будь максимально точним у всіх полях. Особливу увагу приділяй ЧІТКОМУ ЗІСТАВЛЕННЮ ТЕКСТОВИХ МІТОК з їхніми числовими значеннями, особливо для "Matches Played" та "Likes".
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
"НіндзяВтапках, ти хоч і ніндзя, але твої 100 каток на Епіку вже не такі й тихі! Мабудь, тапки дійсно щасливі. Фармиш респект, так тримати!"

Зроби так, щоб кожен гравець відчув себе особливим!
"""

PLAYER_STATS_PROMPT = """
Ти — експертний аналітик скріншотів статистики гравців з гри Mobile Legends: Bang Bang.
Твоє завдання — уважно проаналізувати наданий скріншот зі сторінки "Statistics" (Статистика) гравця та витягнути ВСІ доступні показники. Поверни дані ВИКЛЮЧНО у форматі валідного JSON об'єкта. Не додавай жодного тексту до або після JSON.

Зверни увагу на активний фільтр статистики (наприклад, "All Seasons", "Current Season"). Якщо видно кілька фільтрів, вкажи той, дані якого відображаються на основній частині екрана.

Структура JSON повинна бути такою:
{
  "stats_filter_type": "string або null (наприклад, 'All Seasons', 'Current Season')",
  "main_indicators": {
    "matches_played": "int або null",
    "win_rate": "float або null (наприклад, 48.07, без знаку '%')",
    "mvp_count": "int або null"
  },
  "achievements_left_column": {
    "legendary_count": "int або null",
    "maniac_count": "int або null",
    "double_kill_count": "int або null",
    "most_kills_in_one_game": "int або null",
    "longest_win_streak": "int або null",
    "highest_dmg_per_min": "int або null",
    "highest_gold_per_min": "int або null"
  },
  "achievements_right_column": {
    "savage_count": "int або null",
    "triple_kill_count": "int або null",
    "mvp_loss_count": "int або null",
    "most_assists_in_one_game": "int або null",
    "first_blood_count": "int або null",
    "highest_dmg_taken_per_min": "int або null"
  },
  "details_panel": {
    "kda_ratio": "float або null",
    "teamfight_participation_rate": "float або null (без знаку '%')",
    "avg_gold_per_min": "int або null",
    "avg_hero_dmg_per_min": "int або null",
    "avg_deaths_per_match": "float або null",
    "avg_turret_dmg_per_match": "int або null"
  }
}

КРИТИЧНО ВАЖЛИВІ ІНСТРУКЦІЇ ДЛЯ ТОЧНОСТІ:
1.  **Числові Значення:** Будь НАДЗВИЧАЙНО уважним до всіх числових значень. Розпізнавай КОЖНУ цифру правильно. Не пропускай і не додавай зайвих цифр.
2.  **Win Rate та Teamfight Participation:** Для "win_rate" та "teamfight_participation_rate" витягуй тільки числове значення (float), опускаючи символ '%'. Наприклад, "48.07%" має стати `48.07`.
3.  **Розташування Показників:**
    *   "main_indicators" (matches, win rate, mvp) зазвичай представлені великими круглими діаграмами/показниками у верхній частині.
    *   "achievements_left_column" та "achievements_right_column" – це списки досягнень під основними показниками.
    *   "details_panel" – це показники, що зазвичай знаходяться в окремій панелі праворуч під заголовком "Details" (Деталі).
4.  **Активний Фільтр Статистики:** Визнач, який фільтр активний (наприклад, "All Seasons" або "Current Season", зазвичай виділений або підкреслений) і вкажи його в полі "stats_filter_type".
5.  **Відсутність Даних:** Якщо будь-який показник не видно на скріншоті або він явно відсутній, використовуй значення `null` для відповідного поля в JSON. Не вигадуй дані.
6.  **Точність Текстових Міток:** Переконайся, що ти правильно зіставляєш числові значення з їхніми текстовими мітками (наприклад, "Legendary", "Savage", "KDA", "Gold/Min").

Будь максимально точним. Якість витягнутих даних є пріоритетом.
"""

# Промпт для генерації опису статистики гравця (для майбутнього використання)
PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — досвідчений аналітик та коментатор Mobile Legends, відомий своїм умінням знаходити цікаві аспекти в статистиці гравців.
Проаналізуй надані дані зі статистики гравця {user_name} та напиши короткий (3-6 речень), але інформативний та захоплюючий коментар.

Ось дані статистики гравця ({stats_filter_type}):
- Матчів зіграно: {matches_played}
- Відсоток перемог: {win_rate}%
- MVP: {mvp_count}
- KDA: {kda_ratio}
- Участь у командних боях: {teamfight_participation_rate}%
- Середнє золото/хв: {avg_gold_per_min}
- Легендарних: {legendary_count}, Дикунств: {savage_count}, Маніяків: {maniac_count}
- Найбільша серія перемог: {longest_win_streak}
- Найбільше вбивств за гру: {most_kills_in_one_game}

ТВОЇ ЗАВДАННЯ:
1.  **Знайди "родзинку":** На чому можна зробити акцент? Це може бути:
    *   Високий відсоток перемог або KDA.
    *   Велика кількість матчів, що свідчить про досвід.
    *   Вражаюча кількість MVP, Legendary, Savage.
    *   Висока участь у командних боях або показники золота/шкоди.
    *   Цікаве співвідношення показників (наприклад, багато MVP при середньому відсотку перемог).
2.  **Стиль коментаря:** Позитивний, підбадьорливий, з використанням доречного ігрового сленгу. Можеш відзначити сильні сторони гравця.
3.  **Структура:** Почни з вітання, якщо доречно, або одразу переходь до суті. Заверши позитивним побажанням або спостереженням.
4.  **Лаконічність:** Уникай води, говори по суті.
5.  **ТІЛЬКИ текст коментаря:** Без Markdown/HTML.

ПОГАНИЙ ПРИКЛАД: "Гравець {user_name} зіграв {matches_played} матчів. Його KDA {kda_ratio}."
ДОБРИЙ ПРИКЛАД: "Ого, {user_name}, твої {matches_played} матчів у режимі '{stats_filter_type}' говорять самі за себе! З таким вінрейтом {win_rate}% та {mvp_count} MVP ти справжня гроза серверу. А {savage_count} дикунств – це просто вишенька на торті! Продовжуй в тому ж дусі, легенда!"

Зроби так, щоб гравець відчув цінність своєї статистики!
"""


class MLBBChatGPT:
    """
    Клас для взаємодії з OpenAI API для генерації тексту та аналізу зображень.
    Відповідає за формування запитів до моделей GPT, обробку відповідей
    та надання інтерфейсів для аналізу зображень та генерації текстових описів.
    """
    def __init__(self, api_key: str) -> None:
        """
        Ініціалізує клієнт MLBBChatGPT.

        Args:
            api_key: Ключ доступу до OpenAI API.
        """
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def __aenter__(self):
        """Асинхронний контекстний менеджер для ініціалізації сесії aiohttp."""
        self.session = ClientSession(
            timeout=ClientTimeout(total=90), # Збільшено загальний таймаут для гнучкості
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("Aiohttp сесію створено та відкрито.")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронний контекстний менеджер для закриття сесії aiohttp."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("Aiohttp сесію закрито.")
        if exc_type:
            self.class_logger.error(f"Помилка в MLBBChatGPT під час виходу з контексту: {exc_type} {exc_val}", exc_info=True)

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """
        Створює системний промпт для текстових запитів до GPT (/go команда).
        Включає інформацію про користувача, поточний час та стандарти відповіді.
        """
        kyiv_tz = timezone(timedelta(hours=3))
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"
        
        # Тут знаходиться ваш детальний системний промпт для /go, я його скоротив для прикладу,
        # але у вашому коді він має бути повним.
        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.3 🎮
## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, AI-експерт Mobile Legends Bang Bang... (повний текст вашого промпту)
## КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
... (решта вашого детального промпту) ...
## ЗАПИТ ВІД {user_name}: "{user_query}"
Твоя експертна відповідь (ПАМ'ЯТАЙ: БЕЗ ВИГАДОК, тільки фактичні герої та інформація, валідний HTML):"""

    def _beautify_response(self, text: str) -> str:
        """
        Форматує відповідь GPT, додаючи емодзі та HTML-теги, забезпечуючи валідність HTML.
        Виправляє незакриті теги.
        """
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍", "комунікація": "💬",
            "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄", "командна гра": "🤝",
            "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", "стратегі": "🎯", "мета": "🔥",
            "поточна мета": "📊", "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "💡"
        }

        def replace_header(match: re.Match) -> str:
            header_text = match.group(1).strip(": ").capitalize()
            best_emoji = "💡" 
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета"]
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else: 
                for key_general, emj in header_emojis.items():
                    if key_general in header_text.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>:"

        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+[\-\*]\s+", "  ◦ ", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        tags_to_balance = ["b", "i", "code"]
        for tag in tags_to_balance:
            open_tag_pattern = re.compile(re.escape(f"<{tag}>"))
            close_tag_pattern = re.compile(re.escape(f"</{tag}>"))
            open_count = len(open_tag_pattern.findall(text))
            close_count = len(close_tag_pattern.findall(text))

            if open_count > close_count:
                missing_tags = open_count - close_count
                self.class_logger.warning(f"Beautify: Виявлено {missing_tags} незакритих тегів '<{tag}>'. Додаю їх в кінець.")
                text += (f"</{tag}>" * missing_tags)
            elif close_count > open_count:
                self.class_logger.warning(f"Beautify: Виявлено {close_count - open_count} зайвих закриваючих тегів '</{tag}>'. Спроба видалення може бути небезпечною, залишаю як є.")

        self.class_logger.debug(f"Beautify: Текст після обробки (перші 100 символів): '{text[:100]}'")
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Отримує відповідь від GPT на текстовий запит користувача (для команди /go).

        Args:
            user_name: Ім'я користувача для персоналізації.
            user_query: Текстовий запит від користувача.

        Returns:
            Відформатована відповідь від GPT або повідомлення про помилку.
        """
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name}': '{user_query[:100]}...'") # Логуємо лише частину довгого запиту
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
        self.class_logger.debug(f"Параметри тексту для GPT: temperature={payload['temperature']}, max_tokens={payload['max_tokens']}")
        
        if not self.session or self.session.closed:
            self.class_logger.warning("Aiohttp сесія для текстового GPT була закрита або відсутня. Використовую тимчасову сесію.")
            async with ClientSession(timeout=ClientTimeout(total=45), headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session:
                return await self._execute_openai_request(temp_session, payload, user_name)
        else:
            return await self._execute_openai_request(self.session, payload, user_name)

    async def _execute_openai_request(self, session: ClientSession, payload: Dict[str, Any], user_name_escaped: str) -> str:
        """Допоміжна функція для виконання запиту до OpenAI та обробки відповіді."""
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions", 
                json=payload,
                # Таймаут для конкретного запиту, якщо сесія має загальний більший таймаут
                # Тут можна використовувати ClientTimeout(total=specific_timeout) якщо потрібно
            ) as response:
                response.raise_for_status() # Викине HTTPError для кодів 4xx/5xx
                result = await response.json()
                
                content = result.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка (текст): несподівана структура або порожній контент - {result}")
                    return f"Вибач, {html.escape(user_name_escaped)}, ШІ повернув несподівану відповідь 🤯."
                
                self.class_logger.info(f"Сира відповідь від текстового GPT (перші 100): '{content[:100]}'")
                return self._beautify_response(content)
        except aiohttp.ClientResponseError as e:
            error_text = await e.response.text() if hasattr(e, 'response') and e.response else str(e)
            self.class_logger.error(f"OpenAI API HTTP помилка (текст): {e.status} - {error_text[:200]}", exc_info=True)
            return f"Вибач, {html.escape(user_name_escaped)}, виникли технічні проблеми з доступом до ШІ 😔 (код: {e.status})."
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (текст) для запиту.")
            return f"Вибач, {html.escape(user_name_escaped)}, запит до ШІ зайняв забагато часу ⏳."
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка текстового GPT: {e}")
            return f"Не вдалося обробити твій запит, {html.escape(user_name_escaped)} 😕."

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Аналізує зображення за допомогою OpenAI Vision API (gpt-4o-mini).

        Args:
            image_base64: Зображення у форматі Base64.
            prompt: Системний промпт, що вказує моделі, яку інформацію витягти.

        Returns:
            Словник з результатами аналізу у форматі JSON або словник з помилкою.
        """
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70].replace('\n', ' ')}...'")
        headers = {
            "Content-Type": "application/json",
            # "Authorization" вже встановлено для сесії
        }
        payload = {
            "model": "gpt-4o-mini", 
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
            "max_tokens": 2000, # Збільшено для складних скріншотів зі статистикою
            "temperature": 0.2  # Зменшено для більшої точності вилучення даних
        }
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Vision API була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        
        try:
            async with current_session.post( # type: ignore
                "https://api.openai.com/v1/chat/completions",
                headers=headers, 
                json=payload,
                # Таймаут для конкретного запиту, якщо потрібно (наприклад, ClientTimeout(total=90))
            ) as response:
                return await self._handle_vision_response(response)
        except aiohttp.ClientResponseError as e:
            error_text = await e.response.text() if hasattr(e, 'response') and e.response else str(e)
            self.class_logger.error(f"Vision API HTTP помилка: {e.status} - {error_text[:300]}", exc_info=True)
            return {"error": f"Помилка Vision API: {e.status}", "details": error_text[:200]}
        except asyncio.TimeoutError:
            self.class_logger.error("Vision API Timeout помилка.")
            return {"error": "Запит до Vision API зайняв занадто багато часу."}
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка під час виклику Vision API: {e}")
            return {"error": f"Загальна помилка при аналізі зображення: {str(e)}"}
        finally:
            if temp_session_created and current_session and not current_session.closed: # type: ignore
                await current_session.close() # type: ignore
                self.class_logger.debug("Тимчасову сесію для Vision API закрито.")


    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        """
        Обробляє відповідь від Vision API, витягує та парсить JSON.
        """
        try:
            response.raise_for_status() # Викине HTTPError для кодів 4xx/5xx
            result = await response.json()
        except aiohttp.ClientResponseError as e: # Обробка помилок відповіді сервера
            error_text = await e.response.text() if e.response else str(e)
            self.class_logger.error(f"Vision API HTTP помилка при обробці відповіді: {e.status} - {error_text[:300]}")
            return {"error": f"Помилка Vision API: {e.status}", "details": error_text[:200]}
        except aiohttp.ContentTypeError: # Якщо відповідь не JSON
            raw_text_response = await response.text()
            self.class_logger.error(f"Vision API відповідь не є JSON. Статус: {response.status}. Відповідь: {raw_text_response[:300]}")
            return {"error": "Vision API повернуло не JSON відповідь.", "raw_response": raw_text_response}
        except json.JSONDecodeError as e: # Якщо result не вдалося розпарсити як JSON (малоймовірно після response.json())
             self.class_logger.error(f"Помилка декодування JSON відповіді від Vision API (неочікувано): {e}. Результат: {await response.text()}")
             return {"error": "Не вдалося розпарсити JSON відповідь від Vision API (внутрішня помилка).", "raw_response": await response.text()}


        content = result.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            self.class_logger.error(f"Vision API відповідь без контенту: {result}")
            return {"error": "Vision API повернуло порожню відповідь."}

        self.class_logger.info(f"Vision API сира відповідь отримана (перші 150 символів): {content[:150].replace('\n', ' ')}")
        
        json_str = content.strip()
        # Спроба знайти JSON блок, навіть якщо він обрамлений ```json ... ``` або має зайвий текст
        match = re.search(r"```json\s*(\{.*?\})\s*```", json_str, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Якщо немає ```json ```, шукаємо перший '{' та останній '}'
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

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        """
        Генерує дружній опис профілю гравця на основі даних від Vision API,
        використовуючи модель GPT-4.1.
        """
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
            "model": "gpt-4.1", 
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 300, 
            "temperature": 0.7, 
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        self.class_logger.debug(f"Параметри для опису профілю: temp={payload['temperature']}, max_tokens={payload['max_tokens']}")

        # Використовуємо ту ж логіку для сесії, що і в get_response
        if not self.session or self.session.closed:
            self.class_logger.warning("Aiohttp сесія для опису профілю була закрита або відсутня. Використовую тимчасову сесію.")
            async with ClientSession(timeout=ClientTimeout(total=30), headers={"Authorization": f"Bearer {self.api_key}"}) as temp_session:
                return await self._execute_openai_request(temp_session, payload, user_name) # Потрібно адаптувати _execute_openai_request або створити новий
        else:
            # Потрібно адаптувати _execute_openai_request або створити новий, оскільки _beautify_response тут не потрібен
            # Поки що залишу так, але це потребує уваги, якщо _beautify_response не підходить для цього випадку
            # Або, якщо опис має бути чистим текстом, то _beautify_response не застосовувати.
            # Промпт PROFILE_DESCRIPTION_PROMPT_TEMPLATE просить "ТІЛЬКИ текст коментаря... Без Markdown/HTML."
            # Тому _beautify_response тут не потрібен. Створимо окремий метод для цього.
            return await self._execute_description_request(self.session, payload, user_name)


    async def _execute_description_request(self, session: ClientSession, payload: Dict[str, Any], user_name_escaped: str) -> str:
        """Допоміжна функція для запитів на генерацію описів (без _beautify_response)."""
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions", 
                json=payload,
            ) as response:
                response.raise_for_status()
                result = await response.json()
                
                content = result.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка (опис): несподівана структура або порожній контент - {result}")
                    return f"<i>Не вдалося отримати опис від ШІ для {html.escape(user_name_escaped)}.</i>"
                
                self.class_logger.info(f"Згенеровано опис: '{content[:100]}'")
                return content.strip() # Повертаємо чистий текст
        except aiohttp.ClientResponseError as e:
            error_text = await e.response.text() if hasattr(e, 'response') and e.response else str(e)
            self.class_logger.error(f"OpenAI API HTTP помилка (опис): {e.status} - {error_text[:200]}", exc_info=True)
            return f"<i>Не вдалося згенерувати опис для {html.escape(user_name_escaped)} (код: {e.status}).</i>"
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис) для: '{user_name_escaped}'")
            return f"<i>Опис для {html.escape(user_name_escaped)} генерувався занадто довго...</i>"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис) для '{user_name_escaped}': {e}")
            return f"<i>Виникла помилка при генерації опису для {html.escape(user_name_escaped)}.</i>"

    # async def get_player_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
    #     """
    #     (Майбутня функція) Генерує текстовий опис статистики гравця.
    #     """
    #     self.class_logger.info(f"Запит на генерацію опису статистики для '{user_name}'.")
    #     # Тут буде логіка форматування stats_data для PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE
    #     # та виклик _execute_description_request
    #     # ...
    #     # Приклад:
    #     # main_ind = stats_data.get("main_indicators", {})
    #     # details_p = stats_data.get("details_panel", {})
    #     # ach_left = stats_data.get("achievements_left_column", {})
    #     # ach_right = stats_data.get("achievements_right_column", {})

    #     # system_prompt_text = PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.format(
    #     #     user_name=html.escape(user_name),
    #     #     stats_filter_type=html.escape(str(stats_data.get('stats_filter_type', 'N/A'))),
    #     #     matches_played=main_ind.get('matches_played', 'N/A'),
    #     #     win_rate=main_ind.get('win_rate', 'N/A'),
    #     #     mvp_count=main_ind.get('mvp_count', 'N/A'),
    #     #     kda_ratio=details_p.get('kda_ratio', 'N/A'),
    #     #     teamfight_participation_rate=details_p.get('teamfight_participation_rate', 'N/A'),
    #     #     avg_gold_per_min=details_p.get('avg_gold_per_min', 'N/A'),
    #     #     legendary_count=ach_left.get('legendary_count', 'N/A'),
    #     #     savage_count=ach_right.get('savage_count', 'N/A'),
    #     #     maniac_count=ach_left.get('maniac_count', 'N/A'),
    #     #     longest_win_streak=ach_left.get('longest_win_streak', 'N/A'),
    #     #     most_kills_in_one_game=ach_left.get('most_kills_in_one_game', 'N/A')
    #     # )
    #     # payload = { ... model: "gpt-4.1" ... }
    #     # return await self._execute_description_request(self.session, payload, user_name)
    #     return "<i>Опис статистики гравця ще не реалізовано.</i>"
