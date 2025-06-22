"""
GGenius OpenAI Service Module

Цей модуль забезпечує інтеграцію з OpenAI API для:
- Генерації розумних відповідей на запити користувачів
- Спеціалізованого аналізу скріншотів профілів та статистики MLBB
- Універсального розпізнавання зображень з контекстними відповідями
- Конверсаційної взаємодії з адаптивною поведінкою

Архітектура оптимізована для:
- Високої швидкості обробки
- Ефективного використання ресурсів
- Надійної обробки помилок
- Масштабованості під навантаженням

Author: MLBB-BOSS Team
Version: 3.0 (GGenius Edition)
Python: 3.11+
"""

import asyncio
import base64
import html
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Union, Final
from dataclasses import dataclass
from enum import Enum
import aiohttp
from aiohttp import ClientSession, ClientTimeout


# === КОНФІГУРАЦІЯ МОДЕЛЕЙ ===
class ModelConfig:
    """Конфігурація OpenAI моделей для різних завдань."""
    
    TEXT_MODEL: Final[str] = "gpt-4-1106-preview"  # Основна модель для тексту
    VISION_MODEL: Final[str] = "gpt-4-vision-preview"  # Модель для аналізу зображень
    
    # Параметри для різних типів завдань
    TEXT_PARAMS: Final[Dict[str, Any]] = {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 2000,
        "presence_penalty": 0.3,
        "frequency_penalty": 0.2
    }
    
    VISION_PARAMS: Final[Dict[str, Any]] = {
        "temperature": 0.15,
        "max_tokens": 2500
    }
    
    CONVERSATIONAL_PARAMS: Final[Dict[str, Any]] = {
        "temperature": 0.75,
        "top_p": 0.9,
        "max_tokens": 120,
        "presence_penalty": 0.2,
        "frequency_penalty": 0.2
    }


# === СИСТЕМНІ ПРОМПТИ З РЕБРЕНДИНГОМ НА GGENIUS ===

# Спеціалізовані промпти для Vision API (функціональні, без особистості)
PROFILE_SCREENSHOT_PROMPT: Final[str] = """
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

PLAYER_STATS_PROMPT: Final[str] = """
Ти — MLBB аналітик. Витягни статистику гравця зі скріншота "Statistics". Поверни ТІЛЬКИ JSON.
{
  "stats_filter_type": "string або null ('All Seasons', 'Current Season')",
  "main_indicators": {
    "matches_played": "int або null",
    "win_rate": "float або null (число, без '%')",
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
    "teamfight_participation_rate": "float або null (число, без '%')",
    "avg_gold_per_min": "int або null", 
    "avg_hero_dmg_per_min": "int або null",
    "avg_deaths_per_match": "float або null", 
    "avg_turret_dmg_per_match": "int або null"
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

KESTER_TEXT_EXTRACTION_PROMPT: Final[str] = """
Ти — високоточний сервіс для розпізнавання (OCR) та перекладу тексту, створений для допомоги спільноті GGenius.
Твоє завдання — максимально точно витягнути ВЕСЬ текст, видимий на наданому зображенні.
Після цього, повністю та акуратно переклади витягнутий текст українською мовою.
Результат поверни у вигляді ОДНОГО чистого JSON-об'єкта з єдиним ключем "translated_text".
Значення цього ключа — це повний переклад українською.

ВАЖЛИВО:
1.  **ТІЛЬКИ JSON:** Не додавай жодних пояснень, коментарів або форматування поза структурою JSON.
2.  **Порожнє зображення:** Якщо на зображенні немає тексту, значення "translated_text" має бути порожнім рядком ("").
3.  **Точність:** Розпізнай та переклади текст максимально точно, зберігаючи контекст.
"""

# Промпти для генерації описів з брендингом GGenius
PROFILE_DESCRIPTION_PROMPT_TEMPLATE: Final[str] = """
Ти — GGenius, AI-коментатор MLBB. Створи короткий, дотепний коментар (2-4 речення) про гравця.
Дані:
- Нік: {game_nickname}
- Ранг: {highest_rank_season}
- Матчі: {matches_played}
- Лайки: {likes_received}
- Локація: {location}
- Сквад: {squad_name}

ЗАВДАННЯ:
1.  **Знайди "фішку":** Акцент на вражаючих даних, нікнеймі, скваді, або гумористично обіграй відсутність даних.
2.  **Стиль GGenius:** Захоплення, гумор/іронія (дружня), повага, інтрига. Комбінуй.
3.  **Сленг:** Використовуй доречно ("тащер", "імба", "фармить").
4.  **Унікальність:** Уникай повторень з попередніми коментарями.
5.  **ТІЛЬКИ ТЕКСТ:** Без Markdown/HTML, без привітань.

Приклад (креативно для "НіндзяВтапках", 100 матчів, Епік):
"НіндзяВтапках, твої 100 каток на Епіку вже не такі й тихі! Мабуть, тапки дійсно щасливі."

Зроби гравця особливим!
"""

PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE: Final[str] = """
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
"Ого, {user_name}, твої {matches_played} матчів у '{stats_filter_type}' вражають! Мати {mvp_rate_percent}% MVP-рейт – це сильно! А ефективність золота {damage_per_gold_ratio} показує, що ти знаєш своє діло."

Підкресли унікальність гравця!
"""

# Головний системний промпт для /go режиму
OPTIMIZED_SYSTEM_PROMPT_TEMPLATE: Final[str] = """# GGenius: Твій AI-Наставник 🧠🏆
Привіт, {user_name_escaped}! Я – GGenius, твій персональний AI-наставник та стратегічний аналітик у світі Mobile Legends: Bang Bang.

**Твій Коннект:**
- **Користувач:** {user_name_escaped} (радий допомогти!)
- **Локація:** Telegram-бот **"GGenius"** – твоя секретна зброя для MLBB!
- **На годиннику:** {greeting}, {time_str} – саме час для геніальних інсайтів!

**Як Я Працюю (Мої Правила Гри):**
1.  **Стиль Спілкування (ВАЖЛИВО!):**
    *   **Тон:** Експертний, впевнений, але дружній, неформальний та надихаючий. Я твій ментор, який веде до перемог.
    *   **Гумор:** Сміливо жартуй (можеш навіть трохи легкої самоіронії про себе як AI додати, якщо це в тему).
    *   **Сленг:** Активно, але доречно, використовуй актуальний ігровий та кіберспортивний сленг MLBB (наприклад: "ганк", "фарм", "тащ", "імба", "контра", "роам").
    *   **Емодзі:** Більше фанових, яскравих та виразних емодзі! 🎉😂🔥😎🎮🏆🚀🤯🤔💯💡📈🎯.
    *   **Інтерактивність:** Намагайся не просто закінчувати відповідь, а іноді ставити легке запитання по темі, щоб підтримати діалог.

2.  **Контент (Що по Інфі):**
    *   **Точність та Актуальність:** Інфа має бути чіткою та по темі, базуватися на моїх актуальних знаннях про гру.
    *   **Структура:** Використовуй HTML для оформлення: `<b>жирний</b>` для ключових слів/заголовків, `<i>курсив</i>` для акценту.
    *   **Проактивність:** Якщо питання не зовсім зрозуміле, не бійся уточнити або запропонувати варіанти, як спрацювати краще.

3.  **Унікальність (Моя Суперсила):**
    *   Пам'ятай, що ти – **GGenius**, і твої поради та аналітика є ексклюзивними. Особливо твій **AI-аналіз скріншотів**.

**Моя Спеціалізація (Де Я Геній):**
- **Герої:** Хто кого контрить, топові збірки, як тащити на різних персах.
- **Предмети:** Що, коли і навіщо збирати.
- **Ігрові Механіки:** Фарм, ротації, контроль карти, Лорд/Черепаха, як правильно пушити та дефати.
- **Мета-гра:** Що зараз в тренді, хто імбує, а хто на дні.
- **Стратегії та Тактики:** Драфт (піки/бани), лайнінг, ганки, макро та мікро фішки.
- **Ранги:** Як апнути ранг і не згоріти. 🔥
- **Аналіз скріншотів (моя топ фіча! 📸):** Розбір профілів, статистики, результатів матчів – все по фактам з твоїх скрінів.

**ЗАПИТ ВІД {user_name_escaped}:**
"{user_query_escaped}"

Твоя відповідь має бути чіткою, інформативною, але водночас фановою, з геймерським вайбом! Не забувай, ти GGenius!
"""

# Промпт для конверсаційних відповідей
CONVERSATIONAL_PROMPT_TEMPLATE: Final[str] = """
Ти - GGenius, AI-наставник і друг, учасник Telegram-чату кіберспортивної спільноти MLBB.
Твоє завдання — підтримувати живу розмову.
Стиль: відповідай коротко (1-2 речення), дотепно, неформально, по-людськи. Використовуй молодіжний та ігровий сленг MLBB.
Не будь формальним ботом. Будь "своїм" у компанії.
Звертайся до користувача на ім'я: {user_name}.

Ситуація для відповіді: {trigger_mood}
Історія чату надана для контексту. Твоя відповідь має логічно її продовжувати.
"""

# Універсальний промпт для розпізнавання зображень
UNIVERSAL_VISION_PROMPT_TEMPLATE: Final[str] = """
Ти — GGenius, AI-геймер та аналітик MLBB спільноти. 

🎯 ЗАВДАННЯ: Проаналізуй зображення та дай коротку (1-3 речення), релевантну відповідь як учасник чату.

КОНТЕКСТ КОРИСТУВАЧА:
- Ім'я: {user_name}
- Це Telegram-чат MLBB спільноти
- Очікується природна, дружня реакція

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


# === ТИПИ ДАНИХ ===

@dataclass
class AnalysisResult:
    """Результат аналізу зображення."""
    data: Dict[str, Any]
    description: str
    analysis_type: str
    confidence: float = 1.0
    processing_time: float = 0.0


@dataclass
class APIResponse:
    """Стандартизована відповідь від API."""
    success: bool
    content: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time: float = 0.0


class ResponseType(Enum):
    """Типи відповідей для різних контекстів."""
    TEXT_GENERATION = "text"
    PROFILE_ANALYSIS = "profile"
    STATS_ANALYSIS = "stats"
    UNIVERSAL_VISION = "universal_vision"
    CONVERSATIONAL = "conversational"


# === ОСНОВНИЙ КЛАС СЕРВІСУ ===

class GGeniusAIService:
    """
    Головний сервіс для взаємодії з OpenAI API.
    
    Забезпечує:
    - Генерацію розумних відповідей
    - Спеціалізований аналіз MLBB контенту
    - Ефективне управління ресурсами
    - Надійну обробку помилок
    """
    
    def __init__(self, api_key: str) -> None:
        """
        Ініціалізує сервіс з необхідними параметрами.
        
        Args:
            api_key: OpenAI API ключ для автентифікації
        """
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Лічильники для моніторингу
        self._request_count = 0
        self._total_tokens = 0
        
        self.logger.info(f"GGenius AI Service ініціалізовано. Текст: {ModelConfig.TEXT_MODEL}, Vision: {ModelConfig.VISION_MODEL}")

    async def __aenter__(self) -> "GGeniusAIService":
        """Async context manager entry."""
        self.session = ClientSession(
            timeout=ClientTimeout(total=120),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            connector=aiohttp.TCPConnector(
                limit=100,  # Максимум подключений
                ttl_dns_cache=300,  # Кеш DNS на 5 хвилин
                use_dns_cache=True
            )
        )
        self.logger.debug("Aiohttp сесію створено з оптимізованими параметрами.")
        return self

    async def __aexit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[Any]) -> None:
        """Async context manager exit."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug("Aiohttp сесію закрито.")
        
        if exc_type:
            self.logger.error(f"Помилка в GGenius Service: {exc_type} {exc_val}", exc_info=True)
        
        # Виводимо статистику при закритті
        self.logger.info(f"Статистика сесії: {self._request_count} запитів, ~{self._total_tokens} токенів")

    def _create_dynamic_greeting(self) -> tuple[str, str]:
        """
        Створює динамічне привітання відповідно до часу.
        
        Returns:
            Кортеж (привітання, час_рядок)
        """
        try:
            kyiv_tz = timezone(timedelta(hours=2))  # UTC+2 для України
            current_time = datetime.now(kyiv_tz)
            hour = current_time.hour
            time_str = current_time.strftime('%H:%M (%Z)')

            if 5 <= hour < 12:
                greeting = "Доброго ранку"
            elif 12 <= hour < 17:
                greeting = "Доброго дня"
            elif 17 <= hour < 22:
                greeting = "Доброго вечора"
            else:
                greeting = "Доброї ночі"
                
            return greeting, time_str
            
        except Exception as e:
            self.logger.warning(f"Помилка визначення часу: {e}")
            return "Вітаю", datetime.now(timezone.utc).strftime('%H:%M (UTC)')

    def _create_optimized_prompt(self, user_name: str, user_query: str) -> str:
        """
        Створює оптимізований системний промпт для головного AI.
        
        Args:
            user_name: Ім'я користувача
            user_query: Запит користувача
            
        Returns:
            Готовий системний промпт
        """
        user_name_escaped = html.escape(user_name)
        user_query_escaped = html.escape(user_query)
        greeting, time_str = self._create_dynamic_greeting()

        system_prompt = OPTIMIZED_SYSTEM_PROMPT_TEMPLATE.format(
            user_name_escaped=user_name_escaped,
            greeting=greeting,
            time_str=time_str,
            user_query_escaped=user_query_escaped
        )
        
        self.logger.debug(f"Створено системний промпт довжиною {len(system_prompt)} символів")
        return system_prompt

    def _enhance_response_formatting(self, text: str) -> str:
        """
        Покращує форматування відповіді AI з емодзі та структурою.
        
        Args:
            text: Сирий текст від AI
            
        Returns:
            Відформатований текст з HTML тегами та емодзі
        """
        self.logger.debug(f"Форматування відповіді: {len(text)} символів")
        
        # Мапа емодзі для різних заголовків
        emoji_mapping = {
            "герої": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "герой": "🦸",
            "предмет": "💎", "збірка": "🛠️", "айтем": "💎",
            "тактика": "⚔️", "стратегі": "🎯", "поради": "💡",
            "ранк": "🏆", "рейтинг": "📈", "мета": "🔥",
            "карт": "🗺️", "позиці": "📍", "роташ": "🔄",
            "аналіз": "📊", "статистика": "📈", "данн": "📋",
            "висновок": "🏁", "порад": "💡", "інсайт": "💡"
        }

        def replace_header(match: re.Match) -> str:
            """Замінює заголовки на HTML з емодзі."""
            header_text = match.group(1).strip(": ").capitalize()
            
            # Пошук відповідного емодзі
            emoji = "💡"  # За замовчуванням
            for keyword, emj in emoji_mapping.items():
                if keyword in header_text.lower():
                    emoji = emj
                    break
                    
            return f"\n\n{emoji} <b>{header_text}</b>"

        # Замінюємо markdown заголовки на HTML з емодзі
        text = re.sub(r"^(?:#|\#{2,3})\s*(.+)", replace_header, text, flags=re.MULTILINE)
        
        # Покращуємо списки
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+[\-\*]\s+", "  ◦ ", text, flags=re.MULTILINE)
        
        # Прибираємо зайві переноси
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Балансуємо HTML теги
        self._balance_html_tags(text)
        
        return text.strip()

    def _balance_html_tags(self, text: str) -> str:
        """
        Балансує HTML теги у тексті.
        
        Args:
            text: Текст з потенційно незакритими тегами
            
        Returns:
            Текст з балансованими тегами
        """
        tags_to_balance = ["b", "i", "code", "u", "s"]
        
        for tag in tags_to_balance:
            open_count = text.count(f"<{tag}>")
            close_count = text.count(f"</{tag}>")
            
            if open_count > close_count:
                missing = open_count - close_count
                text += f"</{tag}>" * missing
                self.logger.debug(f"Додано {missing} закриваючих тегів </{tag}>")
        
        return text

    async def _execute_api_request(
        self, 
        payload: Dict[str, Any], 
        response_type: ResponseType,
        user_name: str = "користувач"
    ) -> APIResponse:
        """
        Виконує запит до OpenAI API з обробкою помилок.
        
        Args:
            payload: Дані для API запиту
            response_type: Тип очікуваної відповіді
            user_name: Ім'я користувача для логування
            
        Returns:
            Стандартизована відповідь API
        """
        start_time = asyncio.get_event_loop().time()
        self._request_count += 1
        
        # Створюємо тимчасову сесію якщо основна недоступна
        current_session = self.session
        temp_session_created = False
        
        if not current_session or current_session.closed:
            self.logger.warning("Основна сесія недоступна, створюю тимчасову")
            current_session = ClientSession(
                timeout=ClientTimeout(total=90),
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            temp_session_created = True

        try:
            async with current_session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                response_data = await response.json()
                processing_time = asyncio.get_event_loop().time() - start_time
                
                if response.status != 200:
                    error_details = response_data.get("error", {}).get("message", str(response_data))
                    self.logger.error(f"OpenAI API помилка {response.status}: {error_details}")
                    
                    return APIResponse(
                        success=False,
                        error=f"API помилка {response.status}: {error_details}",
                        processing_time=processing_time
                    )

                content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                if not content:
                    self.logger.error(f"Порожня відповідь API для {response_type.value}")
                    return APIResponse(
                        success=False,
                        error="Отримано порожню відповідь від API",
                        processing_time=processing_time
                    )

                # Оновлюємо статистику токенів
                usage = response_data.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                self._total_tokens += total_tokens
                
                self.logger.info(f"API запит успішний: {processing_time:.2f}с, {total_tokens} токенів")
                
                return APIResponse(
                    success=True,
                    content=content,
                    processing_time=processing_time
                )

        except aiohttp.ClientConnectionError as e:
            self.logger.error(f"Помилка підключення до API: {e}")
            return APIResponse(
                success=False,
                error="Помилка підключення до OpenAI API",
                processing_time=asyncio.get_event_loop().time() - start_time
            )
            
        except asyncio.TimeoutError:
            self.logger.error("Timeout при запиті до API")
            return APIResponse(
                success=False,
                error="Час очікування відповіді від API вичерпано",
                processing_time=asyncio.get_event_loop().time() - start_time
            )
            
        except Exception as e:
            self.logger.exception(f"Неочікувана помилка API: {e}")
            return APIResponse(
                success=False,
                error=f"Системна помилка: {str(e)}",
                processing_time=asyncio.get_event_loop().time() - start_time
            )
            
        finally:
            if temp_session_created and current_session and not current_session.closed:
                await current_session.close()

    async def generate_response(self, user_name: str, user_query: str) -> str:
        """
        Генерує розумну відповідь на запит користувача.
        
        Args:
            user_name: Ім'я користувача
            user_query: Текст запиту
            
        Returns:
            Згенерована відповідь або повідомлення про помилку
        """
        user_name_escaped = html.escape(user_name)
        self.logger.info(f"Генерація відповіді для '{user_name_escaped}': '{user_query[:100]}...'")

        system_prompt = self._create_optimized_prompt(user_name, user_query)
        
        payload = {
            "model": ModelConfig.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": html.escape(user_query)}
            ],
            **ModelConfig.TEXT_PARAMS
        }

        response = await self._execute_api_request(
            payload, 
            ResponseType.TEXT_GENERATION, 
            user_name_escaped
        )

        if not response.success:
            return f"Вибач, {user_name_escaped}, проблема з генерацією відповіді: {response.error} 😔"

        # Форматуємо та повертаємо відповідь
        formatted_response = self._enhance_response_formatting(response.content)
        return formatted_response

    async def _parse_vision_json(self, content: str) -> Optional[Dict[str, Any]]:
        """
        Парсить JSON відповідь від Vision API з покращеною обробкою.
        
        Args:
            content: Сирий контент від API
            
        Returns:
            Розпарсений JSON або None при помилці
        """
        # Прибираємо зайвий текст та шукаємо JSON
        json_str = content.strip()
        
        # Спробуємо знайти JSON блок у markdown
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_str, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Шукаємо JSON за дужками
            start = json_str.find("{")
            end = json_str.rfind("}") + 1
            if start != -1 and end > start:
                json_str = json_str[start:end]

        try:
            parsed_data = json.loads(json_str)
            self.logger.debug("Vision JSON успішно розпарсено")
            return parsed_data
        except json.JSONDecodeError as e:
            self.logger.error(f"Помилка парсингу JSON: {e}. Контент: '{json_str[:200]}'")
            return None

    async def analyze_profile_screenshot(self, image_base64: str, user_name: str) -> Optional[AnalysisResult]:
        """
        Спеціалізований аналіз скріншота профілю MLBB.
        
        Args:
            image_base64: Зображення в base64 форматі
            user_name: Ім'я користувача для персоналізації
            
        Returns:
            Результат аналізу або None при помилці
        """
        user_name_escaped = html.escape(user_name)
        self.logger.info(f"Спеціалізований аналіз профілю від '{user_name_escaped}'")

        start_time = asyncio.get_event_loop().time()

        payload = {
            "model": ModelConfig.VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROFILE_SCREENSHOT_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]
            }],
            **ModelConfig.VISION_PARAMS
        }

        response = await self._execute_api_request(
            payload, 
            ResponseType.PROFILE_ANALYSIS, 
            user_name_escaped
        )

        if not response.success:
            self.logger.error(f"Помилка аналізу профілю: {response.error}")
            return None

        # Парсимо JSON дані
        profile_data = await self._parse_vision_json(response.content)
        if not profile_data:
            return None

        # Генеруємо опис профілю
        description = await self._generate_profile_description(user_name, profile_data)
        
        processing_time = asyncio.get_event_loop().time() - start_time

        return AnalysisResult(
            data=profile_data,
            description=description,
            analysis_type="profile",
            processing_time=processing_time
        )

    async def _generate_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        """
        Генерує опис профілю на основі витягнутих даних.
        
        Args:
            user_name: Ім'я користувача
            profile_data: Дані профілю з Vision API
            
        Returns:
            Згенерований опис
        """
        # Безпечно екрануємо дані для промпту
        safe_data = {}
        for key, value in profile_data.items():
            safe_data[key] = html.escape(str(value)) if value is not None else "Не вказано"

        template_data = {
            "game_nickname": safe_data.get("game_nickname", "Не вказано"),
            "highest_rank_season": safe_data.get("highest_rank_season", "Не вказано"),
            "matches_played": safe_data.get("matches_played", "N/A"),
            "likes_received": safe_data.get("likes_received", "N/A"),
            "location": safe_data.get("location", "Не вказано"),
            "squad_name": safe_data.get("squad_name", "Немає")
        }

        try:
            prompt = PROFILE_DESCRIPTION_PROMPT_TEMPLATE.format(**template_data)
        except KeyError as e:
            self.logger.error(f"Помилка форматування промпту профілю: {e}")
            return f"Помилка генерації опису профілю для {html.escape(user_name)}"

        payload = {
            "model": ModelConfig.TEXT_MODEL,
            "messages": [{"role": "system", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.75,
            "top_p": 0.9
        }

        response = await self._execute_api_request(payload, ResponseType.PROFILE_ANALYSIS, user_name)
        
        if response.success:
            return response.content.strip()
        else:
            return f"Не вдалося згенерувати опис профілю для {html.escape(user_name)}"

    def _calculate_advanced_stats(self, stats_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Розраховує додаткові метрики на основі базової статистики.
        
        Args:
            stats_data: Базові дані статистики
            
        Returns:
            Розширені дані з додатковими метриками
        """
        enhanced = stats_data.copy()
        main_indicators = stats_data.get("main_indicators", {})
        details = stats_data.get("details_panel", {})
        achievements_left = stats_data.get("achievements_left_column", {})
        achievements_right = stats_data.get("achievements_right_column", {})

        derived_stats = {}

        try:
            # Базові показники
            matches_played = main_indicators.get("matches_played")
            win_rate = main_indicators.get("win_rate")
            mvp_count = main_indicators.get("mvp_count")

            # Загальна кількість перемог
            if matches_played and win_rate:
                derived_stats["total_wins"] = int(matches_played * (win_rate / 100))

            # MVP рейтинг у відсотках
            if matches_played and mvp_count and matches_played > 0:
                derived_stats["mvp_rate_percent"] = round((mvp_count / matches_played) * 100, 2)

            # Аналіз Savage частоти
            savage_count = achievements_right.get("savage_count")
            if matches_played and savage_count and matches_played > 0:
                derived_stats["savage_frequency_per_1000_matches"] = round((savage_count / matches_played) * 1000, 2)

            # Ефективність використання золота
            avg_hero_dmg = details.get("avg_hero_dmg_per_min")
            avg_gold = details.get("avg_gold_per_min")
            if avg_hero_dmg and avg_gold and avg_gold > 0:
                derived_stats["damage_per_gold_ratio"] = round(avg_hero_dmg / avg_gold, 2)

            # Частка MVP у перемогах
            total_wins = derived_stats.get("total_wins")
            if total_wins and mvp_count and total_wins > 0:
                derived_stats["mvp_win_share_percent"] = round((mvp_count / total_wins) * 100, 2)

            # Коефіцієнт агресивності (kills per match)
            most_kills = achievements_left.get("most_kills_in_one_game")
            if most_kills and matches_played and matches_played > 0:
                derived_stats["avg_aggression_index"] = round(most_kills / matches_played, 2)

            enhanced["derived_stats"] = derived_stats
            self.logger.debug(f"Розраховано {len(derived_stats)} додаткових метрик")

        except Exception as e:
            self.logger.warning(f"Помилка розрахунку метрик: {e}")
            enhanced["derived_stats"] = {}

        return enhanced

    async def analyze_stats_screenshot(self, image_base64: str, user_name: str) -> Optional[AnalysisResult]:
        """
        Спеціалізований аналіз скріншота статистики MLBB.
        
        Args:
            image_base64: Зображення в base64 форматі
            user_name: Ім'я користувача для персоналізації
            
        Returns:
            Результат аналізу або None при помилці
        """
        user_name_escaped = html.escape(user_name)
        self.logger.info(f"Спеціалізований аналіз статистики від '{user_name_escaped}'")

        start_time = asyncio.get_event_loop().time()

        payload = {
            "model": ModelConfig.VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": PLAYER_STATS_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]
            }],
            **ModelConfig.VISION_PARAMS
        }

        response = await self._execute_api_request(
            payload, 
            ResponseType.STATS_ANALYSIS, 
            user_name_escaped
        )

        if not response.success:
            self.logger.error(f"Помилка аналізу статистики: {response.error}")
            return None

        # Парсимо JSON дані
        stats_data = await self._parse_vision_json(response.content)
        if not stats_data:
            return None

        # Розраховуємо додаткові метрики
        enhanced_stats = self._calculate_advanced_stats(stats_data)

        # Генеруємо опис статистики
        description = await self._generate_stats_description(user_name, enhanced_stats)
        
        processing_time = asyncio.get_event_loop().time() - start_time

        return AnalysisResult(
            data=enhanced_stats,
            description=description,
            analysis_type="statistics",
            processing_time=processing_time
        )

    async def _generate_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
        """
        Генерує опис статистики на основі витягнутих та розрахованих даних.
        
        Args:
            user_name: Ім'я користувача
            stats_data: Повні дані статистики з додатковими метриками
            
        Returns:
            Згенерований опис статистики
        """
        user_name_escaped = html.escape(user_name)

        # Витягуємо дані з різних секцій
        main_ind = stats_data.get("main_indicators", {})
        details_p = stats_data.get("details_panel", {})
        ach_left = stats_data.get("achievements_left_column", {})
        ach_right = stats_data.get("achievements_right_column", {})
        derived_s = stats_data.get("derived_stats", {})

        def safe_get(data_dict: Optional[Dict[str, Any]], key: str, default: Any = "N/A", precision: Optional[int] = None) -> str:
            """Безпечно отримує та форматує значення."""
            if not data_dict:
                return str(default)
            
            value = data_dict.get(key)
            if value is None:
                return str(default)
            
            if isinstance(value, (int, float)) and precision is not None:
                try:
                    return f"{float(value):.{precision}f}"
                except (ValueError, TypeError):
                    return html.escape(str(value))
            
            return html.escape(str(value))

        # Підготовляємо дані для промпту
        template_data = {
            "user_name": user_name_escaped,
            "stats_filter_type": safe_get(stats_data, 'stats_filter_type'),
            "matches_played": safe_get(main_ind, 'matches_played'),
            "win_rate": safe_get(main_ind, 'win_rate'),
            "mvp_count": safe_get(main_ind, 'mvp_count'),
            "kda_ratio": safe_get(details_p, 'kda_ratio', precision=2),
            "teamfight_participation_rate": safe_get(details_p, 'teamfight_participation_rate'),
            "avg_gold_per_min": safe_get(details_p, 'avg_gold_per_min'),
            "legendary_count": safe_get(ach_left, 'legendary_count'),
            "savage_count": safe_get(ach_right, 'savage_count'),
            "maniac_count": safe_get(ach_left, 'maniac_count'),
            "longest_win_streak": safe_get(ach_left, 'longest_win_streak'),
            "most_kills_in_one_game": safe_get(ach_left, 'most_kills_in_one_game'),
            "total_wins": safe_get(derived_s, 'total_wins', default="не розраховано"),
            "mvp_rate_percent": safe_get(derived_s, 'mvp_rate_percent', precision=2),
            "savage_frequency": safe_get(derived_s, 'savage_frequency_per_1000_matches', precision=2),
            "damage_per_gold_ratio": safe_get(derived_s, 'damage_per_gold_ratio', precision=2),
            "mvp_win_share_percent": safe_get(derived_s, 'mvp_win_share_percent', precision=2),
        }

        try:
            prompt = PLAYER_STATS_DESCRIPTION_PROMPT_TEMPLATE.format(**template_data)
        except KeyError as e:
            self.logger.error(f"Помилка форматування промпту статистики: {e}")
            return f"Помилка генерації опису статистики для {user_name_escaped}"

        payload = {
            "model": ModelConfig.TEXT_MODEL,
            "messages": [{"role": "system", "content": prompt}],
            "max_tokens": 300,
            "temperature": 0.73,
            "top_p": 0.9
        }

        response = await self._execute_api_request(payload, ResponseType.STATS_ANALYSIS, user_name)
        
        if response.success:
            return response.content.strip()
        else:
            return f"Не вдалося згенерувати опис статистики для {user_name_escaped}"

    async def analyze_image_universal(self, image_base64: str, user_name: str) -> Optional[str]:
        """
        Універсальний аналіз зображення для чату.
        
        Args:
            image_base64: Зображення в base64 форматі
            user_name: Ім'я користувача для персоналізації
            
        Returns:
            Короткий коментар або None при помилці
        """
        user_name_escaped = html.escape(user_name)
        self.logger.info(f"Універсальний аналіз зображення від '{user_name_escaped}'")

        prompt = UNIVERSAL_VISION_PROMPT_TEMPLATE.format(user_name=user_name_escaped)

        payload = {
            "model": ModelConfig.VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "low"  # Для швидкості
                        }
                    }
                ]
            }],
            "max_tokens": 150,
            "temperature": 0.8,
            "top_p": 0.9
        }

        response = await self._execute_api_request(
            payload, 
            ResponseType.UNIVERSAL_VISION, 
            user_name_escaped
        )

        if not response.success:
            self.logger.error(f"Помилка універсального аналізу: {response.error}")
            return None

        # Очищуємо відповідь від markdown
        clean_response = response.content.strip()
        clean_response = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean_response)
        clean_response = re.sub(r'\*([^*]+)\*', r'\1', clean_response)

        return clean_response

    async def generate_conversational_reply(
        self, 
        user_name: str, 
        chat_history: List[Dict[str, str]], 
        trigger_mood: str
    ) -> str:
        """
        Генерує короткі відповіді для підтримки розмови в чаті.
        
        Args:
            user_name: Ім'я користувача
            chat_history: Історія повідомлень у форматі OpenAI
            trigger_mood: Контекст для відповіді
            
        Returns:
            Згенерована коротка відповідь
        """
        user_name_escaped = html.escape(user_name)
        self.logger.info(f"Генерація конверсаційної відповіді для '{user_name_escaped}'")

        prompt = CONVERSATIONAL_PROMPT_TEMPLATE.format(
            user_name=user_name_escaped,
            trigger_mood=trigger_mood
        )

        messages = [{"role": "system", "content": prompt}] + chat_history

        payload = {
            "model": ModelConfig.TEXT_MODEL,
            "messages": messages,
            **ModelConfig.CONVERSATIONAL_PARAMS
        }

        response = await self._execute_api_request(
            payload, 
            ResponseType.CONVERSATIONAL, 
            user_name_escaped
        )

        if response.success:
            return response.content.strip()
        else:
            self.logger.error(f"Помилка генерації конверсаційної відповіді: {response.error}")
            return f"Вибач, {user_name_escaped}, щось не так з моїм AI-мозком 🤖"


# === BACKWARD COMPATIBILITY ===
# Для сумісності з існуючим кодом, створюємо аліас

class MLBBChatGPT(GGeniusAIService):
    """
    Аліас для зворотної сумісності з існуючим кодом.
    
    @deprecated: Використовуйте GGeniusAIService замість MLBBChatGPT
    """
    
    def __init__(self, api_key: str) -> None:
        super().__init__(api_key)
        self.logger.warning("MLBBChatGPT deprecated. Використовуйте GGeniusAIService")
    
    # Методи для сумісності з існуючим кодом
    async def get_response(self, user_name: str, user_query: str) -> str:
        """Backward compatibility method."""
        return await self.generate_response(user_name, user_query)
    
    async def get_profile_description(self, user_name: str, profile_data: Dict[str, Any]) -> str:
        """Backward compatibility method."""
        return await self._generate_profile_description(user_name, profile_data)
    
    async def get_player_stats_description(self, user_name: str, stats_data: Dict[str, Any]) -> str:
        """Backward compatibility method."""
        return await self._generate_stats_description(user_name, stats_data)


# === МОДУЛЬНІ ФУНКЦІЇ ДЛЯ ЗРУЧНОСТІ ===

async def quick_text_generation(api_key: str, user_name: str, query: str) -> str:
    """
    Швидка генерація тексту без створення класу.
    
    Args:
        api_key: OpenAI API ключ
        user_name: Ім'я користувача
        query: Запит
        
    Returns:
        Згенерована відповідь
    """
    async with GGeniusAIService(api_key) as service:
        return await service.generate_response(user_name, query)


async def quick_image_analysis(api_key: str, image_base64: str, user_name: str, analysis_type: str = "universal") -> Optional[Union[str, AnalysisResult]]:
    """
    Швидкий аналіз зображення.
    
    Args:
        api_key: OpenAI API ключ
        image_base64: Зображення в base64
        user_name: Ім'я користувача
        analysis_type: Тип аналізу ("universal", "profile", "stats")
        
    Returns:
        Результат аналізу
    """
    async with GGeniusAIService(api_key) as service:
        if analysis_type == "profile":
            return await service.analyze_profile_screenshot(image_base64, user_name)
        elif analysis_type == "stats":
            return await service.analyze_stats_screenshot(image_base64, user_name)
        else:
            return await service.analyze_image_universal(image_base64, user_name)


# === ЕКСПОРТ ===
__all__ = [
    "GGeniusAIService",
    "MLBBChatGPT",  # For backward compatibility
    "AnalysisResult",
    "APIResponse",
    "ResponseType",
    "ModelConfig",
    "quick_text_generation",
    "quick_image_analysis"
]