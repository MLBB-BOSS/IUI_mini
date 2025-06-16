import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple

import aiohttp
from aiohttp import ClientSession, ClientTimeout

# === ПРОМПТИ ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ (VISION API) ===

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

# === ПРОМПТИ ДЛЯ ГЕНЕРАЦІЇ ТЕКСТОВИХ ОПИСІВ (GPT-4.1) ===

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

# === КЛАС ДЛЯ ВЗАЄМОДІЇ З OPENAI ===

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
        # Ініціалізація логера для екземпляра класу
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def __aenter__(self) -> "MLBBChatGPT":
        """Асинхронний контекстний менеджер для ініціалізації сесії aiohttp."""
        self.session = ClientSession(
            timeout=ClientTimeout(total=90), # Загальний таймаут для сесії
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("Aiohttp сесію створено та відкрито.")
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """Асинхронний контекстний менеджер для закриття сесії aiohttp."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("Aiohttp сесію закрито.")
        if exc_type:
            self.class_logger.error(f"Помилка в MLBBChatGPT під час виходу з контексту: {exc_type} {exc_val}", exc_info=True)

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """
        Створює детальний системний промпт для текстових запитів до GPT (команда /go).
        Включає інформацію про користувача, поточний час, роль AI, стандарти відповіді,
        та інші важливі інструкції для забезпечення високоякісних та релевантних відповідей.

        Args:
            user_name: Ім'я користувача для персоналізації.
            user_query: Текстовий запит від користувача.

        Returns:
            Повний системний промпт для моделі GPT.
        """
        # Визначення часової зони та поточного часу для персоналізованого вітання
        try:
            kyiv_tz = timezone(timedelta(hours=3)) # UTC+3 для Києва
            current_time_kyiv = datetime.now(kyiv_tz)
            current_hour = current_time_kyiv.hour
            time_str = current_time_kyiv.strftime('%H:%M')
            
            if 5 <= current_hour < 12:
                greeting = "Доброго ранку"
            elif 12 <= current_hour < 17:
                greeting = "Доброго дня"
            elif 17 <= current_hour < 22:
                greeting = "Доброго вечора"
            else:
                greeting = "Доброї ночі"
        except Exception as e:
            self.class_logger.warning(f"Не вдалося визначити київський час, використовую UTC: {e}")
            current_time_utc = datetime.now(timezone.utc)
            greeting = "Вітаю" # Загальне вітання
            time_str = current_time_utc.strftime('%H:%M UTC')

        # !!! ВАЖЛИВО: Це розширений ПРИКЛАД системного промпту. !!!
        # !!! Будь ласка, переконайся, що цей текст відповідає ТВОЄМУ ОРИГІНАЛЬНОМУ детальному промпту. !!!
        # !!! Якщо твій оригінальний промпт відрізняється, ЗАМІНИ цей текст на свій. !!!
        system_prompt = f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.4 🎮
## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI (Intelligent User Interface), висококваліфікований AI-експерт та аналітик гри Mobile Legends: Bang Bang (MLBB). Твоя місія – надавати гравцям точну, глибоку та корисну інформацію, стратегічні поради та аналітику світового рівня. Ти завжди доброзичливий, терплячий та прагнеш допомогти користувачеві досягти нових висот у грі. Ти володієш енциклопедичними знаннями про всіх героїв, їхні навички, предмети, ігрові механіки, поточну мету, стратегії та тактики на всіх етапах гри.

## КОНТЕКСТ СПІЛКУВАННЯ
- **Ім'я користувача:** {html.escape(user_name)}
- **Поточний час:** {greeting.lower()} ({time_str})
- **Платформа:** Telegram-бот

## ОСНОВНІ ПРИНЦИПИ ТА СТАНДАРТИ ВІДПОВІДІ
1.  **Точність та Актуальність:** Інформація повинна бути максимально точною та відповідати поточній версії гри (враховуй останні оновлення, балансні правки, зміни в меті). Якщо не впевнений, краще зазнач це, ніж надай невірну інформацію. Уникай вигадок.
2.  **Глибина та Деталізація:** Надавай розгорнуті відповіді, пояснюй складні концепції простими словами. Не обмежуйся поверхневими порадами.
3.  **Структурованість:** Використовуй чітку структуру: заголовки (виділені жирним та з відповідним емодзі), списки (марковані • та ◦), абзаци. Це полегшує сприйняття інформації.
4.  **HTML-форматування:** Твої відповіді повинні використовувати базове HTML-форматування для кращої читабельності:
    *   `<b>жирний текст</b>` для заголовків, ключових термінів.
    *   `<i>курсив</i>` для акцентів або назв (наприклад, <i>Winter Truncheon</i>).
    *   `<code>кодовий стиль</code>` для ID предметів, специфічних ігрових команд або технічних термінів, якщо доречно.
    *   Використовуй емодзі для візуального збагачення та передачі настрою (див. розділ "Емодзі").
    *   Переконуйся, що всі HTML-теги правильно закриті.
5.  **Проактивність та Повнота:** Якщо запит користувача нечіткий, спробуй уточнити його або надай декілька варіантів відповіді, що охоплюють можливі інтерпретації. Передбачай можливі додаткові питання користувача.
6.  **Індивідуальний Підхід:** Звертайся до користувача на ім'я ({html.escape(user_name)}). Адаптуй стиль відповіді під контекст запиту.
7.  **Безпека та Етика:** Не надавай шкідливих порад, не використовуй образливу лексику. Дотримуйся етичних норм спілкування.
8.  **Мова:** Відповідай українською мовою, дотримуючись граматичних та стилістичних норм.

## СПЕЦІАЛІЗАЦІЯ ТА ТЕМИ
Ти експерт у таких темах:
- **Герої:** Детальний аналіз навичок, збірок предметів, контр-піків, синергій, ролі в команді, тактики гри за конкретного героя.
- **Предмети:** Опис ефектів, ситуативне застосування, оптимальні збірки для різних ролей та героїв.
- **Ігрові Механіки:** Фарм, ротації, контроль карти, об'єктиви (Лорд, Черепаха), пуш ліній, захист бази, командні бої.
- **Мета-гра:** Аналіз поточної мети, популярні герої та стратегії на різних рангах.
- **Стратегії та Тактики:** Драфт, лайнінг, ганки, макро- та мікро-гра.
- **Рангова Система:** Поради щодо підняття рангу, особливості гри на різних етапах.
- **Кіберспорт:** Аналіз професійних матчів (якщо є дані), турнірні стратегії.

## ЕМОДЗІ-ГАЙД (використовуй доречно)
- Загальні: 💡 (ідея, порада), 🎯 (ціль, стратегія), ⚔️ (бій, тактика), 🛡️ (захист, предмети), 💰 (фарм, золото), 📈 (покращення, навички), 🏆 (ранг, досягнення), 🗺️ (карта, ротації), 🦸/🦸‍♂️/🦸‍♀️ (герої), ✨ (синергія, особливий ефект), 🔥 (мета, популярне), 📊 (статистика, аналіз), 🤔 (роздуми, питання), ✅ (правильно, підтвердження), ❌ (неправильно, застереження).
- Специфічні для ролей: 🏹 (Стрілець), 🗡️ (Вбивця), 🧙 (Маг), 💪 (Боєць), 🛡️ (Танк), ❤️ (Підтримка).

## ФОРМАТ ВІДПОВІДІ НА ЗАПИТ КОРИСТУВАЧА
Починай відповідь з короткого вітання або підтвердження теми, якщо доречно.
Далі структуруй інформацію, використовуючи заголовки та списки.
Завершуй відповідь позитивним побажанням або пропозицією допомогти ще.

## ЗАПИТ ВІД {html.escape(user_name)}: "{html.escape(user_query)}"
Твоя експертна та детальна відповідь (ПАМ'ЯТАЙ ПРО HTML, ЕМОДЗІ ТА СТРУКТУРУ):
"""
        self.class_logger.debug(f"Згенеровано системний промпт для /go. Довжина: {len(system_prompt)} символів.")
        return system_prompt

    def _beautify_response(self, text: str) -> str:
        """
        Форматує відповідь GPT, додаючи емодзі до заголовків та HTML-теги для списків,
        забезпечуючи валідність HTML та виправляючи незакриті теги.

        Args:
            text: Сирий текст відповіді від GPT.

        Returns:
            Відформатований текст для відображення користувачеві.
        """
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
        
        # Емодзі для заголовків на основі ключових слів
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍", "комунікація": "💬",
            "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄", "командна гра": "🤝",
            "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", "стратегі": "🎯", "мета": "🔥",
            "поточна мета": "📊", "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "💡", "предмет": "🛡️", "збірка": "🛠️",
            "аналіз": "📊", "статистика": "📈", "оновлення": "⚙️", "баланс": "⚖️"
        }

        def replace_header(match: re.Match) -> str:
            header_text = match.group(1).strip(": ").capitalize()
            # Пріоритет для більш конкретних ключів
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета", "предмет", "збірка"]
            best_emoji = "💡" # Дефолтний емодзі для порад/загальних заголовків
            
            found_specific = False
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    found_specific = True
                    break
            if not found_specific:
                for key_general, emj in header_emojis.items():
                    if key_general in header_text.lower():
                        best_emoji = emj
                        break
            return f"\n\n{best_emoji} <b>{header_text}</b>:"

        # Заміна Markdown-подібних заголовків на HTML з емодзі
        text = re.sub(r"^(?:##|###)\s*(.+)", replace_header, text, flags=re.MULTILINE)
        
        # Заміна Markdown-подібних списків на HTML-сумісні
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE) # Основний рівень списку
        text = re.sub(r"^\s*•\s+[\-\*]\s+", "  ◦ ", text, flags=re.MULTILINE) # Вкладений рівень списку

        # Видалення зайвих порожніх рядків
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Балансування HTML тегів
        tags_to_balance = ["b", "i", "code"]
        for tag in tags_to_balance:
            open_tag_pattern = re.compile(re.escape(f"<{tag}>"))
            close_tag_pattern = re.compile(re.escape(f"</{tag}>"))
            
            # Обережне виправлення: тільки якщо є явний дисбаланс
            open_tags = [m.start() for m in open_tag_pattern.finditer(text)]
            close_tags = [m.start() for m in close_tag_pattern.finditer(text)]

            open_count = len(open_tags)
            close_count = len(close_tags)

            if open_count > close_count:
                # Додаємо закриваючі теги в кінці тексту, якщо їх не вистачає
                missing_tags_count = open_count - close_count
                text += f"</{tag}>" * missing_tags_count
                self.class_logger.warning(f"Beautify: Додано {missing_tags_count} незакритих тегів '</{tag}>' в кінці тексту.")
            # Зайві закриваючі теги складніше безпечно видалити без повного DOM-парсера, тому їх ігноруємо,
            # сподіваючись, що Telegram клієнт впорається або модель не буде їх генерувати.
            elif close_count > open_count:
                 self.class_logger.warning(f"Beautify: Виявлено {close_count - open_count} зайвих закриваючих тегів '</{tag}>'. Залишено без змін.")


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
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name_escaped}': '{user_query[:100]}...'")
        system_prompt = self._create_smart_prompt(user_name, user_query) # user_name не екранується для внутрішнього промпту
        
        payload = {
            "model": "gpt-4.1-turbo", # Або інша актуальна потужна модель
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html.escape(user_query)} # Екрануємо запит користувача для безпеки
            ],
            "max_tokens": 1500, # Збільшено для більш детальних відповідей
            "temperature": 0.6, # Збалансована температура
            "top_p": 0.9,      
            "presence_penalty": 0.2, 
            "frequency_penalty": 0.1 
        }
        self.class_logger.debug(f"Параметри для GPT (/go): модель={payload['model']}, temperature={payload['temperature']}, max_tokens={payload['max_tokens']}")
        
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для GPT (/go) була закрита або відсутня. Створюю тимчасову сесію.")
            # Використовуємо той самий таймаут, що й для основної сесії
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        
        try:
            return await self._execute_openai_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для GPT (/go) закрито.")


    async def _execute_openai_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        """
        Допоміжна функція для виконання запиту до OpenAI Chat Completions API та обробки відповіді.
        Застосовує _beautify_response до успішної відповіді.
        """
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions", 
                json=payload,
                # Таймаут для конкретного запиту можна встановити тут, якщо потрібно
                # timeout=ClientTimeout(total=60) 
            ) as response:
                response_data = await response.json() # Читаємо відповідь один раз
                if response.status != 200: # Обробка HTTP помилок
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка: {response.status} - {error_details[:300]}")
                    # Уникаємо подвійного екранування, якщо user_name_for_error_msg вже екранований
                    return f"Вибач, {user_name_for_error_msg}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status})."

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка: несподівана структура або порожній контент - {response_data}")
                    return f"Вибач, {user_name_for_error_msg}, ШІ повернув несподівану відповідь 🤯."
                
                self.class_logger.info(f"Сира відповідь від GPT (перші 100): '{content[:100]}'")
                return self._beautify_response(content)
        
        except aiohttp.ClientConnectionError as e: # Проблеми з'єднання
            self.class_logger.error(f"OpenAI API помилка з'єднання: {e}", exc_info=True)
            return f"Вибач, {user_name_for_error_msg}, не вдалося з'єднатися з сервісом ШІ 🌐. Спробуй пізніше."
        except asyncio.TimeoutError: # Таймаут запиту
            self.class_logger.error(f"OpenAI API Timeout для запиту.")
            return f"Вибач, {user_name_for_error_msg}, запит до ШІ зайняв забагато часу ⏳."
        except Exception as e: # Інші непередбачені помилки
            self.class_logger.exception(f"Загальна помилка GPT: {e}")
            return f"Не вдалося обробити твій запит, {user_name_for_error_msg} 😕."

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
        
        payload = {
            "model": "gpt-4o", 
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
            "max_tokens": 2500, # Збільшено для складних скріншотів зі статистикою
            "temperature": 0.15  # Дуже низька температура для максимальної точності вилучення даних
        }
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Vision API була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        
        try:
            # Використовуємо ClientSession, який гарантовано не None
            async with current_session.post( # type: ignore[union-attr]
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                # Таймаут для конкретного запиту, якщо потрібно (наприклад, ClientTimeout(total=90))
            ) as response:
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
            if temp_session_created and current_session and not current_session.closed: # type: ignore[comparison-overlap]
                await current_session.close() # type: ignore[union-attr]
                self.class_logger.debug("Тимчасову сесію для Vision API закрито.")


    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        """
        Обробляє відповідь від Vision API, витягує та парсить JSON.
        """
        response_text = await response.text() # Читаємо текст відповіді для логування та обробки помилок

        try:
            if response.status != 200: # Обробка HTTP помилок
                self.class_logger.error(f"Vision API HTTP помилка: {response.status} - {response_text[:300]}")
                try: # Спробуємо розпарсити помилку як JSON, якщо можливо
                    error_data = json.loads(response_text)
                    error_message = error_data.get("error", {}).get("message", response_text)
                except json.JSONDecodeError:
                    error_message = response_text
                return {"error": f"Помилка Vision API: {response.status}", "details": error_message[:200]}

            result = json.loads(response_text) # Парсимо успішну відповідь
        
        except json.JSONDecodeError: # Якщо відповідь не JSON, навіть при статусі 200 (малоймовірно)
            self.class_logger.error(f"Vision API відповідь не є валідним JSON. Статус: {response.status}. Відповідь: {response_text[:300]}")
            return {"error": "Vision API повернуло не JSON відповідь.", "raw_response": response_text}
        
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
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на генерацію опису профілю для '{user_name_escaped}'.")

        # Екрануємо дані профілю перед вставкою в промпт
        escaped_profile_data = {
            k: html.escape(str(v)) if v is not None else "Не вказано" 
            for k, v in profile_data.items()
        }

        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(
            user_name=user_name_escaped, # Вже екрановано
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
            "max_tokens": 350, 
            "temperature": 0.75, # Трохи вища температура для креативності
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1
        }
        self.class_logger.debug(f"Параметри для опису профілю: модель={payload['model']}, temp={payload['temperature']}, max_tokens={payload['max_tokens']}")

        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для опису профілю була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        
        try:
            return await self._execute_description_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed: # type: ignore[comparison-overlap]
                await current_session.close() # type: ignore[union-attr]
                self.class_logger.debug("Тимчасову сесію для опису профілю закрито.")

    async def _execute_description_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        """
        Допоміжна функція для виконання запиту до OpenAI Chat Completions API для генерації описів.
        Не застосовує _beautify_response, оскільки очікується чистий текст.
        """
        try:
            async with session.post( # type: ignore[union-attr]
                "https://api.openai.com/v1/chat/completions", 
                json=payload,
                # timeout=ClientTimeout(total=45) # Таймаут для конкретного запиту
            ) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка (опис): {response.status} - {error_details[:300]}")
                    return f"<i>Не вдалося згенерувати опис для {user_name_for_error_msg} (код: {response.status}).</i>"
                
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка (опис): порожній контент - {response_data}")
                    return f"<i>Не вдалося отримати опис від ШІ для {user_name_for_error_msg}.</i>"
                
                self.class_logger.info(f"Згенеровано опис (перші 100): '{content[:100]}'")
                return content.strip() # Повертаємо чистий текст
        
        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"OpenAI API помилка з'єднання (опис): {e}", exc_info=True)
            return f"<i>Не вдалося з'єднатися з сервісом ШІ для генерації опису ({user_name_for_error_msg}).</i>"
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис) для: '{user_name_for_error_msg}'")
            return f"<i>Опис для {user_name_for_error_msg} генерувався занадто довго...</i>"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис) для '{user_name_for_error_msg}': {e}")
            return f"<i>Виникла помилка при генерації опису для {user_name_for_error_msg}.</i>"

    # async def get_player_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
    #     """
    #     (Майбутня функція) Генерує текстовий опис статистики гравця.
    #     """
    #     user_name_escaped = html.escape(user_name)
    #     self.class_logger.info(f"Запит на генерацію опису статистики для '{user_name_escaped}'.")
        
    #     # Приклад витягнення та підготовки даних для шаблону
    #     main_ind = stats_data.get("main_indicators", {})
    #     details_p = stats_data.get("details_panel", {})
    #     ach_left = stats_data.get("achievements_left_column", {})
    #     ach_right = stats_data.get("achievements_right_column", {})

    #     # Екранування даних перед вставкою в шаблон
    #     template_data = {
    #         "user_name": user_name_escaped,
    #         "stats_filter_type": html.escape(str(stats_data.get('stats_filter_type', 'N/A'))),
    #         "matches_played": main_ind.get('matches_played', 'N/A'),
    #         "win_rate": main_ind.get('win_rate', 'N/A'), # Припускаємо, що це вже float
    #         "mvp_count": main_ind.get('mvp_count', 'N/A'),
    #         "kda_ratio": details_p.get('kda_ratio', 'N/A'), # Припускаємо, що це вже float
    #         "teamfight_participation_rate": details_p.get('teamfight_participation_rate', 'N/A'), # Припускаємо, що це вже float
    #         "avg_gold_per_min": details_p.get('avg_gold_per_min', 'N/A'),
    #         "legendary_count": ach_left.get('legendary_count', 'N/A'),
    #         "savage_count": ach_right.get('savage_count', 'N/A'),
    #         "maniac_count": ach_left.get('maniac_count', 'N/A'),
    #         "longest_win_streak": ach_left.get('longest_win_streak', 'N/A'),
    #         "most_kills_in_one_game": ach_left.get('most_kills_in_one_game', 'N/A')
    #     }
    #     # Забезпечуємо, що всі значення є рядками для безпечного форматування
    #     for key, value in template_data.items():
    #         if not isinstance(value, str):
    #             template_data[key] = str(value)


    #     system_prompt_text = PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.format(**template_data)
        
    #     payload = {
    #         "model": "gpt-4.1-turbo", 
    #         "messages": [{"role": "system", "content": system_prompt_text}],
    #         "max_tokens": 400, 
    #         "temperature": 0.7, 
    #         "top_p": 0.9
    #     }
    #     self.class_logger.debug(f"Параметри для опису статистики: модель={payload['model']}, temp={payload['temperature']}, max_tokens={payload['max_tokens']}")
        
    #     current_session = self.session
    #     temp_session_created = False
    #     if not current_session or current_session.closed:
    #         self.class_logger.warning("Aiohttp сесія для опису статистики була закрита або відсутня. Створюю тимчасову сесію.")
    #         current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
    #         temp_session_created = True
        
    #     try:
    #         return await self._execute_description_request(current_session, payload, user_name_escaped)
    #     finally:
    #         if temp_session_created and current_session and not current_session.closed:
    #             await current_session.close()
    #             self.class_logger.debug("Тимчасову сесію для опису статистики закрито.")
        
    #     # Повернемо заглушку, поки функція не реалізована повністю
    #     await asyncio.sleep(0) # Для асинхронності, якщо немає реальних await викликів
    #     return "<i>Опис статистики гравця наразі в розробці.</i>"
