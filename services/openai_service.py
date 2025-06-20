import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

import aiohttp
from aiohttp import ClientSession, ClientTimeout

from config import logger, OPENAI_API_KEY, TEXT_MODEL, VISION_MODEL

# === ПРОМПТИ ДЛЯ АНАЛІЗУ ЗОБРАЖЕНЬ (VISION API) ===
PROFILE_SCREENSHOT_PROMPT = """
Ти — MLBB аналітик. Витягни дані з скріншота профілю. Поверни ТІЛЬКИ JSON.
{
  "game_nickname": "string або null",
  "mlbb_id_server": "string 'ID (SERVER)' або null (приклад: '123456789 (1234)')",
  "highest_rank_season": "string (приклад: 'Міфічна Слава 267 ★') або null",
  "matches_played": "int або null (знизу скріншота)",
  "likes_received": "int або null (знизу скріншота)",
  "location": "string або null",
  "squad_name": "string або null"
}
ВАЖЛИВО:
1.  **ID/Server (mlbb_id_server):** Шукай біля іконки профілю. Формат 'ID (SERVER)'.
2.  **Матчі (Matches Played) / Лайки (Likes Received):** Знаходяться ВНИЗУ. Не плутай з очками популярності.
3.  **Найвищий Ранг (Highest Rank):** Під написом "Highest Rank". Включай зірки/очки.
4.  **Сквад (Squad Name):** Повна назва.
5.  **Відсутні дані:** Використовуй `null`.
Точність є критичною.
"""

PLAYER_STATS_PROMPT = """
Ти — MLBB аналітик. Витягни статистику гравця зі скріншота "Statistics". Поверни ТІЛЬКИ JSON.
{
  "stats_filter_type": "string або null ('All Seasons', 'Current Season')",
  "main_indicators": {
    "matches_played": "int або null",
    "win_rate": "float або null (число, без '%')",
    "mvp_count": "int або null"
  },
  "achievements_left_column": {
    "legendary_count": "int або null", "maniac_count": "int або null", "double_kill_count": "int або null",
    "most_kills_in_one_game": "int або null", "longest_win_streak": "int або null",
    "highest_dmg_per_min": "int або null", "highest_gold_per_min": "int або null"
  },
  "achievements_right_column": {
    "savage_count": "int або null", "triple_kill_count": "int або null", "mvp_loss_count": "int або null",
    "most_assists_in_one_game": "int або null", "first_blood_count": "int або null",
    "highest_dmg_taken_per_min": "int або null"
  },
  "details_panel": {
    "kda_ratio": "float або null", "teamfight_participation_rate": "float або null (число, без '%')",
    "avg_gold_per_min": "int або null", "avg_hero_dmg_per_min": "int або null",
    "avg_deaths_per_match": "float або null", "avg_turret_dmg_per_match": "int або null"
  }
}
ВАЖЛИВО:
1.  **Числа:** Уважно розпізнавай кожну цифру.
2.  **Win Rate / Teamfight Participation:** Тільки число (float), без '%'.
3.  **Розташування:** "main_indicators" - зверху; "achievements" - списки нижче; "details_panel" - справа.
4.  **Фільтр:** Вкажи активний фільтр ('All Seasons'/'Current Season').
5.  **Відсутні дані:** Використовуй `null`.
Точність є критичною.
"""

KESTER_TEXT_EXTRACTION_PROMPT = """
Ти — високоточний сервіс для розпізнавання (OCR) та перекладу тексту, створений для допомоги спільноті.
Твоє завдання — максимально точно витягнути ВЕСЬ текст, видимий на наданому зображенні.
Після цього, повністю та акуратно переклади витягнутий текст українською мовою.
Результат поверни у вигляді ОДНОГО чистого JSON-об'єкта з єдиним ключем "translated_text".
Значення цього ключа — це повний переклад українською.
ВАЖЛИВО:
1.  **ТІЛЬКИ JSON:** Не додавай жодних пояснень, коментарів або форматування поза структурою JSON.
2.  **Порожнє зображення:** Якщо на зображенні немає тексту, значення "translated_text" має бути порожнім рядком ("").
3.  **Точність:** Розпізнай та переклади текст максимально точно, зберігаючи контекст.
"""

# === ПРОМПТИ ДЛЯ ГЕНЕРАЦІЇ ОПИСІВ ===
PROFILE_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — коментатор MLBB. Створи короткий, дотепний коментар (2-4 речення) про гравця.
Дані:
- Нік: {game_nickname}
- Ранг: {highest_rank_season}
- Матчі: {matches_played}
- Лайки: {likes_received}
- Локація: {location}
- Сквад: {squad_name}
ЗАВДАННЯ:
1.  **Знайди "фішку":** Акцент на вражаючих даних, нікнеймі, скваді, або гумористично обіграй відсутність даних.
2.  **Стиль:** Захоплення, гумор/іронія (дружня), повага, інтрига. Комбінуй.
3.  **Сленг:** Використовуй доречно ("тащер", "імба", "фармить").
4.  **Унікальність:** Уникай повторень з попередніми коментарями.
5.  **ТІЛЬКИ ТЕКСТ:** Без Markdown/HTML, без привітань.
Приклад (креативно для "НіндзяВтапках", 100 матчів, Епік):
"НіндзяВтапках, твої 100 каток на Епіку вже не такі й тихі! Мабуть, тапки дійсно щасливі."
Зроби гравця особливим!
"""

PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE = """
Ти — аналітик MLBB. Напиши короткий (3-5 речень) коментар про статистику гравця {user_name}.
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
1.  **Знайди "родзинку":** Акцент на високих показниках (Win Rate, KDA, MVP Рейтинг), кількості матчів/перемог, Savage тощо.
2.  **Стиль:** Позитивний, підбадьорливий, з доречним ігровим сленгом.
3.  **ТІЛЬКИ ТЕКСТ:** Без Markdown/HTML.
Приклад:
"Ого, {user_name}, твої {matches_played} матчів у '{stats_filter_type}' вражають! Мати {mvp_rate_percent}% MVP-рейт – це сильно! А ефективність з[...]"
Підкресли унікальність гравця!
"""

# === ОПТИМІЗОВАНИЙ СИСТЕМНИЙ ПРОМПТ ДЛЯ /GO ===
OPTIMIZED_SYSTEM_PROMPT_TEMPLATE = """# MLBB ГУРУ IUI 😎🎮
Йо, {user_name_escaped}! Я – IUI, твій персональний AI-кореш та топ-аналітик по Mobile Legends: Bang Bang, ексклюзивно тут, в **"IUI mini"**!

**Твій Коннект:**
- **Користувач:** {user_name_escaped} (радий бачити!)
- **Локація:** Telegram-бот **"IUI mini"** – твоя секретна зброя для MLBB!
- **На годиннику:** {greeting}, {time_str} – саме час для крутих інсайтів!

**Як Я Працюю (Мої Правила Гри):**
1.  **Стиль Спілкування (ВАЖЛИВО!):**
    *   **Тон:** Молодіжний, дружній, неформальний, веселий та трохи зухвалий (по-доброму!). Будь як свій чувак з тім[...]
    *   **Гумор:** Сміливо жартуй (можеш навіть трохи **легкої самоіронії про себе як AI додати, якщо це в тему і не пе[...]
    *   **Сленг:** Активно, але доречно, використовуй актуальний ігровий та кіберспортивний сленг MLBB (наприклад: "т[...]
    *   **Емодзі:** Більше фанових, яскравих та виразних емодзі! 🎉😂🔥😎🎮🏆🚀🤯🤔💯💡📈🎯.
    *   **Інтерактивність:** Намагайся не просто закінчувати відповідь, а іноді ставити легке запитання по темі, щ[...]

2.  **Контент (Що по Інфі):**
    *   **Точність та Актуальність:** Інфа має бути чіткою та по темі, базуватися на моїх актуальних знаннях про гр[...]
    *   **Структура:** Використовуй HTML для оформлення: `<b>жирний</b>` для ключових слів/заголовків, `<i>курсив</i>` для а[...]
    *   **Проактивність:** Якщо питання не зовсім зрозуміле, не бійся уточнити або запропонувати варіанти, як спра[...]

3.  **Унікальність (Моя Суперсила):**
    *   Пам'ятай, що ти – **IUI, твій персональний гуру в боті "IUI mini"**, і саме тут, в **"IUI mini"**, твої фішки, особливо **AI-а[...]

**Моя Спеціалізація (Де Я Шаря):**
- **Герої:** Хто кого контрить, топові збірки, як тащити на різних персах.
- **Предмети:** Що, коли і навіщо збирати.
- **Ігрові Механіки:** Фарм, ротації, контроль карти, Лорд/Черепаха, як правильно пушити та дефати.
- **Мета-гра:** Що зараз в тренді, хто імбує, а хто на дні.
- **Стратегії та Тактики:** Драфт (піки/бани), лайнінг, ганки, макро та мікро фішки.
- **Ранги:** Як апнути ранг і не згоріти. 🔥
- **Аналіз скріншотів (моя топ фіча! 📸):** Розбір профілів, статистики, результатів матчів – все по фактам з тво[...]

**ЗАПИТ ВІД {user_name_escaped}:**
"{user_query_escaped}"

Твоя відповідь має бути чіткою, інформативною, але водночас фановою, з приколами та геймерським вайбом! Не за[...]
"""

# === ПРОМПТ ДЛЯ ТРИГЕРНИХ ВІДПОВІДЕЙ ===
CONVERSATIONAL_PROMPT_TEMPLATE = """
Ти - AI-асистент GGenius, друг і учасник Telegram-чату кіберспортивної спільноти MLBB.
Твоє завдання — підтримувати живу розмову.
Стиль: відповідай коротко (1-2 речення), дотепно, неформально, по-людськи. Використовуй молодіжний та ігровий сленг, де це доречно.
Не будь формальним ботом. Будь "своїм" у компанії.
Звертайся до користувача на ім'я: {user_name}.
Ситуація для відповіді: {trigger_mood}
Історія чату надана для контексту. Твоя відповідь має логічно її продовжувати.
"""

# === КЛАС MLBBChatGPT ===
class MLBBChatGPT:
    TEXT_MODEL = "gpt-4.1"
    VISION_MODEL = "gpt-4.1-mini"

    AVAILABLE_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "create_lobby",
                "description": "Створює ігрове лобі з заданими параметрами.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "size": {"type": "integer", "description": "Розмір лобі (2-5 гравців)."},
                        "role": {"type": "string", "description": "Роль ініціатора (Танк, Маг тощо)."}
                    },
                    "required": ["size", "role"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_screenshot",
                "description": "Аналізує скріншот профілю або статистики.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "screenshot_type": {"type": "string", "enum": ["profile", "stats"], "description": "Тип скріншота."}
                    },
                    "required": ["screenshot_type"]
                }
            }
        }
    ]

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

    def _create_smart_prompt_optimized(self, user_name: str, user_query: str) -> str:
        user_name_escaped = html.escape(user_name)
        user_query_escaped = html.escape(user_query)
        try:
            current_time_utc = datetime.now(timezone.utc)
            kyiv_tz = timezone(timedelta(hours=3))
            current_time_kyiv = current_time_utc.astimezone(kyiv_tz)
            current_hour_kyiv = current_time_kyiv.hour
            time_str = current_time_kyiv.strftime('%H:%M (%Z)')
            if 5 <= current_hour_kyiv < 12:
                greeting = "Доброго ранку"
            elif 12 <= current_hour_kyiv < 17:
                greeting = "Доброго дня"
            elif 17 <= current_hour_kyiv < 22:
                greeting = "Доброго вечора"
            else:
                greeting = "Доброї ночі"
        except Exception as e:
            self.class_logger.warning(f"Не вдалося визначити київський час: {e}")
            current_time_utc_fallback = datetime.now(timezone.utc)
            greeting = "Вітаю"
            time_str = current_time_utc_fallback.strftime('%H:%M (UTC)')
        system_prompt = OPTIMIZED_SYSTEM_PROMPT_TEMPLATE.format(
            user_name_escaped=user_name_escaped,
            greeting=greeting,
            time_str=time_str,
            user_query_escaped=user_query_escaped
        )
        self.class_logger.debug(f"Згенеровано оптимізований системний промпт. Довжина: {len(system_prompt)}")
        return system_prompt

    def _beautify_response(self, text: str) -> str:
        self.class_logger.debug(f"Beautify: Початковий текст (перші 100 символів): '{text[:100]}'")
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
            for key in priority_keys:
                if key in header_text_raw.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else:
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

    async def get_response(self, user_name: str, user_query: str) -> str:
        user_name_escaped = html.escape(user_name)
        user_query_for_payload = html.escape(user_query)
        self.class_logger.info(f"Запит до GPT (/go) від '{user_name_escaped}': '{user_query[:100]}...'")
        system_prompt = self._create_smart_prompt_optimized(user_name, user_query)
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query_for_payload}
            ],
            "max_tokens": 2000,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2
        }
        self.class_logger.debug(f"Параметри для GPT (/go): модель={payload['model']}")
        current_session = self.session
        temp_session_created = False
        if not current_session or current_session.closed:
            self.class_logger.warning("Aiohttp сесія для GPT (/go) була закрита. Створюю тимчасову.")
            current_session = ClientSession(timeout=ClientTimeout(total=120), headers={"Authorization": f"Bearer {self.api_key}"})
            temp_session_created = True
        try:
            return await self._execute_openai_request(current_session, payload, user_name_escaped)
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()
                self.class_logger.debug("Тимчасову сесію для GPT (/go) закрито.")

    async def _execute_openai_request(self, session: ClientSession, payload: Dict[str, Any], user_name_for_error_msg: str) -> str:
        try:
            async with session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.class_logger.error(f"OpenAI API HTTP помилка: {response.status} - {error_details}")
                    return f"Сорян, {user_name_for_error_msg}, трабл з доступом до AI 😔 (код: {response.status})."
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.class_logger.error(f"OpenAI API помилка: порожній контент - {response_data}")
                    return f"Отакої, {user_name_for_error_msg}, AI мовчить 🤯."
                self.class_logger.info(f"Сира відповідь від GPT: '{content[:100]}'")
                return self._beautify_response(content)
        except Exception as e:
            self.class_logger.error(f"Помилка в _execute_openai_request: {e}", exc_info=True)
            return f"Щось пішло не так, {user_name_for_error_msg} 😕."

    async def get_response_with_history(self, history: List[Dict[str, str]]) -> str:
        self.class_logger.info(f"Контекстний запит. Історія: {len(history)} повідомлень.")
        messages = [{"role": "system", "content": self._create_smart_prompt_optimized("користувач", "")}] + history
        payload = {
            "model": self.TEXT_MODEL,
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 0.7,
            "top_p": 0.9,
            "tools": self.AVAILABLE_TOOLS
        }
        try:
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as resp:
                data = await resp.json()
                choice = data["choices"][0]["message"]
                if "tool_calls" in choice:
                    tool_call = choice["tool_calls"][0]["function"]
                    function_name = tool_call["name"]
                    arguments = json.loads(tool_call["arguments"])
                    return self._handle_function_call(function_name, arguments)
                return choice["content"].strip()
        except Exception as e:
            self.class_logger.error(f"Помилка в get_response_with_history: {e}", exc_info=True)
            raise

    def _handle_function_call(self, function_name: str, arguments: Dict[str, Any]) -> str:
        self.class_logger.info(f"Виклик функції: {function_name} з аргументами {arguments}")
        if function_name == "create_lobby":
            size = arguments["size"]
            role = arguments["role"]
            return f"<b>Створюю лобі!</b> Розмір: {size}, твоя роль: {role}. Підтверди в чаті!"
        elif function_name == "analyze_screenshot":
            screenshot_type = arguments["screenshot_type"]
            return f"<b>Аналізую скріншот!</b> Тип: {screenshot_type}. Кидай фото, я розберу!"
        return "<i>Функція в розробці, брате! Скоро буде вогонь.</i>"

    async def analyze_image_with_vision(self, image_base64: str, prompt: str) -> Optional[Dict[str, Any]]:
        self.class_logger.info(f"Запит до Vision API. Промпт: '{prompt[:70]}...'")
        payload = {
            "model": self.VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                    ]
                }
            ],
            "max_tokens": 2500,
            "temperature": 0.15
        }
        try:
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                return await self._handle_vision_response(response)
        except Exception as e:
            self.class_logger.error(f"Помилка в analyze_image_with_vision: {e}", exc_info=True)
            return {"error": f"Не вдалося проаналізувати зображення: {str(e)}"}

    async def _handle_vision_response(self, response: aiohttp.ClientResponse) -> Optional[Dict[str, Any]]:
        response_text = await response.text()
        try:
            if response.status != 200:
                self.class_logger.error(f"Vision API HTTP помилка: {response.status} - {response_text[:300]}")
                error_message = response_text
                try:
                    error_data = json.loads(response_text)
                    error_message = error_data.get("error", {}).get("message", response_text)
                except json.JSONDecodeError:
                    pass
                return {"error": f"Помилка Vision API: {response.status}", "details": error_message[:200]}
            result = json.loads(response_text)
            content = result.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                self.class_logger.error(f"Vision API відповідь без контенту: {result}")
                return {"error": "Vision API повернуло порожню відповідь."}
            self.class_logger.info(f"Vision API сира відповідь: {content[:150]}")
            json_str = content.strip()
            match = re.search(r"```json\s*(\{.*?\})\s*```", json_str, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                start_brace = json_str.find("{")
                end_brace = json_str.rfind("}")
                if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
                    json_str = json_str[start_brace:end_brace + 1]
                else:
                    self.class_logger.error(f"Не вдалося знайти JSON блок: '{content[:300]}'")
                    return {"error": "Не вдалося вилучити JSON з відповіді.", "raw_response": content}
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            self.class_logger.error(f"Помилка декодування JSON: {e}. Рядок: '{json_str[:300]}'")
            return {"error": "Не вдалося розпарсити JSON відповідь.", "raw_response": content}

    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на опис профілю для '{user_name_escaped}'.")
        escaped_profile_data = {k: html.escape(str(v)) if v is not None else "Не вказано" for k, v in profile_data.items()}
        template_payload = {
            "game_nickname": escaped_profile_data.get("game_nickname", "Не вказано"),
            "highest_rank_season": escaped_profile_data.get("highest_rank_season", "Не вказано"),
            "matches_played": escaped_profile_data.get("matches_played", "N/A"),
            "likes_received": escaped_profile_data.get("likes_received", "N/A"),
            "location": escaped_profile_data.get("location", "Не вказано"),
            "squad_name": escaped_profile_data.get("squad_name", "Немає"),
        }
        system_prompt_text = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(**template_payload)
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 200,
            "temperature": 0.75,
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1
        }
        try:
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                self.class_logger.info(f"Згенеровано опис профілю: '{content[:100]}'")
                return content.strip()
        except Exception as e:
            self.class_logger.error(f"Помилка в get_profile_description: {e}", exc_info=True)
            return f"<i>Не вдалося згенерувати опис для {user_name_escaped}. Щось пішло не так...</i>"

    async def get_player_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на опис статистики для '{user_name_escaped}'.")
        main_ind = stats_data.get("main_indicators", {})
        details_p = stats_data.get("details_panel", {})
        ach_left = stats_data.get("achievements_left_column", {})
        ach_right = stats_data.get("achievements_right_column", {})
        def get_value(data_dict: Dict[str, Any], key: str, default_val: Any = "N/A", precision: Optional[int] = None) -> str:
            val = data_dict.get(key)
            if val is None:
                return str(default_val)
            if isinstance(val, (int, float)) and precision is not None:
                return f"{float(val):.{precision}f}"
            return html.escape(str(val))
        template_data = {
            "user_name": user_name_escaped,
            "stats_filter_type": stats_data.get("stats_filter_type", "N/A"),
            "matches_played": get_value(main_ind, "matches_played"),
            "win_rate": get_value(main_ind, "win_rate"),
            "mvp_count": get_value(main_ind, "mvp_count"),
            "kda_ratio": get_value(details_p, "kda_ratio", precision=2),
            "teamfight_participation_rate": get_value(details_p, "teamfight_participation_rate"),
            "avg_gold_per_min": get_value(details_p, "avg_gold_per_min"),
            "legendary_count": get_value(ach_left, "legendary_count"),
            "savage_count": get_value(ach_right, "savage_count"),
            "maniac_count": get_value(ach_left, "maniac_count"),
            "longest_win_streak": get_value(ach_left, "longest_win_streak"),
            "most_kills_in_one_game": get_value(ach_left, "most_kills_in_one_game"),
            "total_wins": "N/A",
            "mvp_rate_percent": "N/A",
            "savage_frequency": "N/A",
            "damage_per_gold_ratio": "N/A",
            "mvp_win_share_percent": "N/A",
        }
        system_prompt_text = PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.format(**template_data)
        payload = {
            "model": self.TEXT_MODEL,
            "messages": [{"role": "system", "content": system_prompt_text}],
            "max_tokens": 250,
            "temperature": 0.73,
            "top_p": 0.9,
            "presence_penalty": 0.15,
            "frequency_penalty": 0.15
        }
        try:
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                self.class_logger.info(f"Згенеровано опис статистики: '{content[:100]}'")
                return content.strip()
        except Exception as e:
            self.class_logger.error(f"Помилка в get_player_stats_description: {e}", exc_info=True)
            return f"<i>Не вдалося згенерувати опис статистики для {user_name_escaped}. Щось пішло не так...</i>"

    async def generate_conversational_reply(self, user_name: str, chat_history: List[Dict[str, str]], trigger_mood: str) -> str:
        user_name_escaped = html.escape(user_name)
        self.class_logger.info(f"Запит на розмовну відповідь для '{user_name_escaped}' з тригером '{trigger_mood}'.")
        system_prompt = CONVERSATIONAL_PROMPT_TEMPLATE.format(user_name=user_name_escaped, trigger_mood=trigger_mood)
        messages = [{"role": "system", "content": system_prompt}] + chat_history
        payload = {
            "model": self.TEXT_MODEL,
            "messages": messages,
            "max_tokens": 120,
            "temperature": 0.75,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.2
        }
        try:
            async with self.session.post("https://api.openai.com/v1/chat/completions", json=payload) as response:
                response_data = await response.json()
                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                self.class_logger.info(f"Згенеровано розмовну відповідь: '{content[:100]}'")
                return content.strip()
        except Exception as e:
            self.class_logger.error(f"Помилка в generate_conversational_reply: {e}", exc_info=True)
            return f"Йо, {user_name_escaped}, щось пішло не так, але я ще тут!"
