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

# === ПРОМПТИ ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ (VISION API) ===
# ... (PROFILE_SCREENSHOT_PROMPT та PLAYER_STATS_PROMPT залишаються без змін, вони довгі, тому я їх тут скорочую) ...
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

# === ПРОМПТИ ДЛЯ ГЕНЕРАЦІЇ ТЕКСТОВИХ ОПИСІВ (GPT-4 Turbo) ===
# ... (PROFILE_DESCRIPTION_PROMPT_TEMPLATE залишається без змін) ...
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
- MVP: {mvp_count} (з них {mvp_rate_percent}% від усіх матчів)
- KDA: {kda_ratio}
- Участь у командних боях: {teamfight_participation_rate}%
- Середнє золото/хв: {avg_gold_per_min}
- Легендарних: {legendary_count}, Дикунств: {savage_count} (приблизно {savage_frequency} на 1000 матчів), Маніяків: {maniac_count}
- Найбільша серія перемог: {longest_win_streak}
- Найбільше вбивств за гру: {most_kills_in_one_game}
- Ефективність золота (шкода/золото): {damage_per_gold_ratio}
- Частка MVP у перемогах: {mvp_win_share_percent}%
- Загалом перемог: {total_wins}

ТВОЇ ЗАВДАННЯ:
1.  **Знайди "родзинку":** На чому можна зробити акцент? Використовуй ЯК БАЗОВІ, ТАК І УНІКАЛЬНІ РОЗРАХОВАНІ показники. Це може бути:
    *   Високий відсоток перемог, KDA, або **MVP Рейтинг ({mvp_rate_percent}%)**.
    *   Велика кількість матчів ({matches_played}) або **загальна кількість перемог ({total_wins})**.
    *   Вражаюча кількість MVP, Legendary, Savage (особливо якщо **частота Savage ({savage_frequency})** висока).
    *   **Ефективність золота ({damage_per_gold_ratio})**: якщо вона висока, це означає, що гравець добре конвертує фарм у шкоду.
    *   **Частка MVP у перемогах ({mvp_win_share_percent}%)**: високий показник означає, що MVP гравця дійсно ведуть до перемоги.
    *   Висока участь у командних боях або показники золота/шкоди.
    *   Цікаве співвідношення показників.
2.  **Стиль коментаря:** Позитивний, підбадьорливий, з використанням доречного ігрового сленгу ("тащер", "фармила", "кіберкотлета", "розриває"). Можеш відзначити сильні сторони гравця, базуючись на всіх даних.
3.  **Структура:** Почни з вітання, якщо доречно, або одразу переходь до суті. Заверши позитивним побажанням або спостереженням.
4.  **Лаконічність:** Уникай води, говори по суті.
5.  **ТІЛЬКИ текст коментаря:** Без Markdown/HTML.

ПОГАНИЙ ПРИКЛАД: "Гравець {user_name} зіграв {matches_played} матчів. Його KDA {kda_ratio}."
ДОБРИЙ ПРИКЛАД (з урахуванням нових даних):
"Ого, {user_name}, твої {matches_played} матчів у '{stats_filter_type}' – це просто космос! Мати {mvp_rate_percent}% MVP-рейт – це сильно! А ефективність золота {damage_per_gold_ratio} показує, що ти справжній економіст на полі бою, що конвертує кожну монетку в чисту шкоду. {savage_count} дикунств, навіть якщо це {savage_frequency} на тисячу ігор, – це завжди епічно! Так тримати, чемпіоне!"

Зроби так, щоб гравець відчув цінність своєї статистики та унікальних розрахунків!
"""

# === КЛАС ДЛЯ ВЗАЄМОДІЇ З OPENAI ===

class MLBBChatGPT:
    TEXT_MODEL = "gpt-4.1" 
    VISION_MODEL = "gpt-4.1-mini"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.class_logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.class_logger.info(f"MLBBChatGPT ініціалізовано. Текстова модель: {self.TEXT_MODEL}, Vision модель: {self.VISION_MODEL}")

    async def __aenter__(self) -> "MLBBChatGPT":
        self.session = ClientSession(
            timeout=ClientTimeout(total=90),
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        self.class_logger.debug("Aiohttp сесію створено та відкрито.")
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            self.class_logger.debug("Aiohttp сесію закрито.")
        if exc_type:
            self.class_logger.error(f"Помилка в MLBBChatGPT під час виходу з контексту: {exc_type} {exc_val}", exc_info=True)

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        # ... (код _create_smart_prompt залишається без змін) ...
        try:
            kyiv_tz = timezone(timedelta(hours=3)) 
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
            greeting = "Вітаю" 
            time_str = current_time_utc.strftime('%H:%M UTC')

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
        # ... (код _beautify_response залишається без змін) ...
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
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
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета", "предмет", "збірка"]
            best_emoji = "💡" 
            
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

        text = re.sub(r"^(?:##|###)\s*(.+)", replace_header, text, flags=re.MULTILINE)
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

    async def get_response(self, user_name: str, user_query: str) -> str:
        # ... (код get_response залишається без змін) ...
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name_escaped}': '{user_query[:100]}...'")
        system_prompt = self._create_smart_prompt(user_name, user_query)
        
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html.escape(user_query)}
            ],
            "max_tokens": 1500,
            "temperature": 0.6,
            "top_p": 0.9,      
            "presence_penalty": 0.2, 
            "frequency_penalty": 0.1 
        }
        self.class_logger.debug(f"Параметри для GPT (/go): модель={payload['model']}, temperature={payload['temperature']}, max_tokens={payload['max_tokens']}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для GPT (/go) була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            return await self._execute_openai_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для GPT (/go) закрито.")

    async def _execute_openai_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        # ... (код _execute_openai_request залишається без змін) ...
        try:
            async with session.post(
                "https://api.openai.com/v1/chat/completions", 
                json=payload,
            ) as response:
                response_data = await response.json() 
                if response.status != 200: 
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка: {response.status} - {error_details}")
                    return f"Вибач, {user_name_for_error_msg}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status})."

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка: несподівана структура або порожній контент - {response_data}")
                    return f"Вибач, {user_name_for_error_msg}, ШІ повернув несподівану відповідь 🤯."
                
                self.class_logger.info(f"Сира відповідь від GPT (перші 100): '{content[:100]}'")
                return self._beautify_response(content)
        
        except aiohttp.ClientConnectionError as e: 
            self.class_logger.error(f"OpenAI API помилка з'єднання: {e}", exc_info=True)
            return f"Вибач, {user_name_for_error_msg}, не вдалося з'єднатися з сервісом ШІ 🌐. Спробуй пізніше."
        except asyncio.TimeoutError: 
            self.class_logger.error(f"OpenAI API Timeout для запиту.")
            return f"Вибач, {user_name_for_error_msg}, запит до ШІ зайняв забагато часу ⏳."
        except Exception as e: 
            self.class_logger.exception(f"Загальна помилка GPT: {e}")
            return f"Не вдалося обробити твій запит, {user_name_for_error_msg} 😕."

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        # ... (код analyze_image_with_vision залишається без змін) ...
        self.class_logger.info(f"Запит до Vision API. Промпт починається з: '{prompt[:70].replace('\n', ' ')}...'")
        payload = {
            "model": self.VISION_MODEL,
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
            "max_tokens": 2500,
            "temperature": 0.15
        }
        self.class_logger.debug(f"Параметри для Vision API: модель={payload['model']}, max_tokens={payload['max_tokens']}, temperature={payload['temperature']}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для Vision API була закрита або відсутня. Створюю тимчасову сесію.")
            current_session = ClientSession(timeout=ClientTimeout(total=90), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            async with current_session.post( 
                "https://api.openai.com/v1/chat/completions",
                json=payload,
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
            if temp_session_created and current_session and not current_session.closed: 
                await current_session.close() 
                self.class_logger.debug("Тимчасову сесію для Vision API закрито.")

    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        # ... (код _handle_vision_response залишається без змін) ...
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

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        # ... (код get_profile_description залишається без змін) ...
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на генерацію опису профілю для '{user_name_escaped}'.")
        escaped_profile_data = {
            k: html.escape(str(v)) if v is not None else "Не вказано" 
            for k, v in profile_data.items()
        }
        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(
            user_name=user_name_escaped,
            game_nickname=escaped_profile_data.get("game_nickname", "Не вказано"),
            highest_rank_season=escaped_profile_data.get("highest_rank_season", "Не вказано"),
            matches_played=escaped_profile_data.get("matches_played", "N/A"),
            likes_received=escaped_profile_data.get("likes_received", "N/A"),
            location=escaped_profile_data.get("location", "Не вказано"),
            squad_name=escaped_profile_data.get("squad_name", "Немає"),
        )
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 350, 
            "temperature": 0.75,
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
            if temp_session_created and current_session and not current_session.closed: 
                await current_session.close() 
                self.class_logger.debug("Тимчасову сесію для опису профілю закрито.")

    async def _execute_description_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        # ... (код _execute_description_request залишається без змін) ...
        try:
            async with session.post( 
                "https://api.openai.com/v1/chat/completions", 
                json=payload,
            ) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка (опис): {response.status} - {error_details}")
                    return f"<i>Не вдалося згенерувати опис для {user_name_for_error_msg} (код: {response.status}).</i>"
                
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка (опис): порожній контент - {response_data}")
                    return f"<i>Не вдалося отримати опис від ШІ для {user_name_for_error_msg}.</i>"
                
                self.class_logger.info(f"Згенеровано опис (перші 100): '{content[:100]}'")
                return content.strip()
        
        except aiohttp.ClientConnectionError as e:
            self.class_logger.error(f"OpenAI API помилка з'єднання (опис): {e}", exc_info=True)
            return f"<i>Не вдалося з'єднатися з сервісом ШІ для генерації опису ({user_name_for_error_msg}).</i>"
        except asyncio.TimeoutError:
            self.class_logger.error(f"OpenAI API Timeout (опис) для: '{user_name_for_error_msg}'")
            return f"<i>Опис для {user_name_for_error_msg} генерувався занадто довго...</i>"
        except Exception as e:
            self.class_logger.exception(f"Загальна помилка (опис) для '{user_name_for_error_msg}': {e}")
            return f"<i>Виникла помилка при генерації опису для {user_name_for_error_msg}.</i>"

    async def get_player_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
        """
        Генерує текстовий опис статистики гравця на основі даних від Vision API
        та розрахованих унікальних статистик.
        """
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на генерацію опису статистики для '{user_name_escaped}' (з унікальними даними).")
        
        # Базові дані
        main_ind = stats_data.get("main_indicators", {})
        details_p = stats_data.get("details_panel", {})
        ach_left = stats_data.get("achievements_left_column", {})
        ach_right = stats_data.get("achievements_right_column", {})
        
        # Розраховані дані (derived_stats)
        derived_s = stats_data.get("derived_stats", {}) # Отримуємо словник розрахованих статистик

        # Функція для безпечного отримання та форматування значення
        def get_value(data_dict: Optional[Dict[str, Any]], key: str, default_val: Any = "N/A", precision: Optional[int] = None) -> str:
            if data_dict is None:
                return str(default_val)
            val = data_dict.get(key)
            if val is None:
                return str(default_val)
            if precision is not None:
                try:
                    return f"{float(val):.{precision}f}"
                except (ValueError, TypeError):
                    return html.escape(str(val)) # Якщо не вдалося форматувати як float
            return html.escape(str(val))

        template_data = {
            "user_name": user_name_escaped,
            "stats_filter_type": get_value(stats_data, 'stats_filter_type'),
            "matches_played": get_value(main_ind, 'matches_played'),
            "win_rate": get_value(main_ind, 'win_rate'),
            "mvp_count": get_value(main_ind, 'mvp_count'),
            "kda_ratio": get_value(details_p, 'kda_ratio', precision=2),
            "teamfight_participation_rate": get_value(details_p, 'teamfight_participation_rate'),
            "avg_gold_per_min": get_value(details_p, 'avg_gold_per_min'),
            "legendary_count": get_value(ach_left, 'legendary_count'),
            "savage_count": get_value(ach_right, 'savage_count'),
            "maniac_count": get_value(ach_left, 'maniac_count'),
            "longest_win_streak": get_value(ach_left, 'longest_win_streak'),
            "most_kills_in_one_game": get_value(ach_left, 'most_kills_in_one_game'),
            # Додаємо розраховані статистики
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
            "model": self.TEXT_MODEL, 
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 450, # Трохи більше токенів для потенційно довших описів з новими даними
            "temperature": 0.73, 
            "top_p": 0.9,
            "presence_penalty": 0.15,
            "frequency_penalty": 0.15
        }
        self.class_logger.debug(f"Параметри для опису статистики (з derived): модель={payload['model']}, temp={payload['temperature']}, max_tokens={payload['max_tokens']}")
        
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
