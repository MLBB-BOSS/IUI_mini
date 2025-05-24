"""
MLBB Expert Bot - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.

Революційне рішення для кіберспортивної MLBB спільноти з світовими стандартами якості.

Python 3.11+ | aiogram 3.19+ | OpenAI GPT-4o-mini
Author: MLBB-BOSS | Date: 2025-05-24
Version: 2.1.0
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiohttp import ClientSession, ClientTimeout, ClientError
from dotenv import load_dotenv

# === КОНСТАНТИ ТА КОНФІГУРАЦІЯ ===

# Версія та метадані
BOT_VERSION: str = "2.1.0"
BUILD_DATE: str = "2025-05-24"
MAX_RESPONSE_TOKENS: int = 300
REQUEST_TIMEOUT: int = 30
GPT_MODEL: str = "gpt-4o-mini"

# Налаштування логування для професійної діагностики
LOG_FORMAT: str = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | "
    "%(funcName)s() | %(message)s"
)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            filename=f"mlbb_bot_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
            mode="a"
        )
    ]
)

# Оптимізація логерів для продуктивності
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Завантаження змінних середовища
load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

# Валідація критичних параметрів
if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    error_msg = "❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі"
    logger.critical(error_msg)
    raise RuntimeError(error_msg)

logger.info(f"✅ Конфігурація завантажена успішно | Версія: {BOT_VERSION}")

# === ЕНУМЕРАЦІЇ ТА ТИПИ ===

class GameStrategy(Enum):
    """Типи ігрових стратегій для кращої категоризації."""
    SOLO = "solo"
    DUO = "duo"
    TRIO = "trio"
    TEAM = "team"
    RANKED = "ranked"


class ResponseQuality(Enum):
    """Рівні якості відповідей для моніторингу."""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"


@dataclass
class PerformanceMetrics:
    """Метрики продуктивності для оптимізації."""
    response_time: float
    token_count: int
    success_rate: float
    user_satisfaction: Optional[float] = None


# === РОЗУМНИЙ GPT АСИСТЕНТ ===

class MLBBExpertGPT:
    """
    Революційний GPT асистент для MLBB з найвищими стандартами якості.
    
    Оптимізований для швидкості, точності та користувацького досвіду.
    Спеціалізований на Mobile Legends Bang Bang без застарілої інформації.
    """
    
    # Кеш для оптимізації повторних запитів
    _response_cache: Dict[str, Tuple[str, float]] = {}
    _cache_ttl: int = 300  # 5 хвилин
    
    def __init__(self, api_key: str) -> None:
        """
        Ініціалізує GPT асистента з професійними налаштуваннями.
        
        Args:
            api_key: OpenAI API ключ для аутентифікації
        """
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        self.success_count = 0
        
        logger.info("🧠 MLBB Expert GPT ініціалізовано")
    
    async def __aenter__(self) -> "MLBBExpertGPT":
        """Асинхронний контекст менеджер - вхід."""
        timeout = ClientTimeout(total=REQUEST_TIMEOUT, connect=10)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"MLBB-Expert-Bot/{BOT_VERSION}"
        }
        
        self.session = ClientSession(timeout=timeout, headers=headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Асинхронний контекст менеджер - вихід з очисткою ресурсів."""
        if self.session:
            await self.session.close()
            logger.debug("🔄 GPT сесію закрито")
    
    def _create_expert_system_prompt(self, user_name: str) -> str:
        """
        Створює експертний системний промпт без згадок про дати та версії.
        
        Args:
            user_name: Ім'я користувача для персоналізації
            
        Returns:
            Оптимізований системний промпт
        """
        current_hour = datetime.now().hour
        
        # Динамічне привітання залежно від часу
        if 5 <= current_hour < 12:
            greeting = "Доброго ранку"
        elif 12 <= current_hour < 17:
            greeting = "Доброго дня"
        elif 17 <= current_hour < 22:
            greeting = "Доброго вечора"
        else:
            greeting = "Доброї ночі"
        
        return f"""
🎮 {greeting}, {user_name}! Ти спілкуєшся з топовим MLBB експертом у кіберспортивній спільноті!

ТВОЯ ЕКСПЕРТИЗА: Mobile Legends Bang Bang професійний коуч та аналітик.

✅ ТВОЇ СУПЕРСИЛИ:
• Розробляєш стратегії для соло, дуо, тріо та командної гри
• Аналізуєш ігрові ситуації та даєш тактичні поради
• Пояснюєш складні механіки простими словами
• Допомагаєш з позиціонуванням та ротаціями
• Навчаєш читати карту та передбачати дії ворогів
• Мотивуєш та розвиваєш ментальність переможця

🚫 ОБМЕЖЕННЯ:
• НЕ рекомендуй конкретні білди предметів
• НЕ вказуй точні артефакти або емблеми  
• НЕ згадуй дати оновлень, патчів або версії гри
• НЕ використовуй HTML теги або markdown
• НЕ давай інформацію про поточну мету

💬 СТИЛЬ ЕКСПЕРТА:
- Звертайся до {user_name} як до рівного гравця
- Використовуй емодзі для структурування
- Будь впевненим та натхненним
- Ділися досвідом як про-гравець
- Максимум 200 слів - коротко та по суті
- Структуруй поради чітко та логічно

🎯 ФОКУС НА НАВИЧКАХ:
Розвивай навички гравця, а не залежність від конкретних білдів!

Готовий зробити з {user_name} справжнього про-гравця MLBB! 🏆
"""
    
    def _generate_cache_key(self, user_query: str, user_name: str) -> str:
        """
        Генерує унікальний ключ для кешування запитів.
        
        Args:
            user_query: Запит користувача
            user_name: Ім'я користувача
            
        Returns:
            Хеш ключ для кешу
        """
        combined = f"{user_query.lower().strip()}_{len(user_name)}_{datetime.now().hour}"
        return str(hash(combined))
    
    def _clean_cache(self) -> None:
        """Очищує застарілі записи з кешу для оптимізації пам'яті."""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._response_cache.items()
            if current_time - timestamp > self._cache_ttl
        ]
        
        for key in expired_keys:
            del self._response_cache[key]
        
        if expired_keys:
            logger.debug(f"🧹 Очищено {len(expired_keys)} застарілих записів кешу")
    
    async def get_expert_response(self, user_name: str, user_query: str) -> Tuple[str, PerformanceMetrics]:
        """
        Отримує експертну відповідь від GPT з метриками продуктивності.
        
        Args:
            user_name: Ім'я користувача
            user_query: Запит користувача
            
        Returns:
            Кортеж з відповіддю та метриками продуктивності
        """
        if not self.session:
            raise RuntimeError("❌ GPT сесію не ініціалізовано")
        
        start_time = time.time()
        self.request_count += 1
        
        # Перевіряємо кеш для оптимізації
        cache_key = self._generate_cache_key(user_query, user_name)
        current_time = time.time()
        
        if cache_key in self._response_cache:
            cached_response, timestamp = self._response_cache[cache_key]
            if current_time - timestamp < self._cache_ttl:
                logger.info(f"📋 Кешована відповідь для {user_name}")
                
                metrics = PerformanceMetrics(
                    response_time=time.time() - start_time,
                    token_count=len(cached_response.split()),
                    success_rate=1.0
                )
                
                return cached_response, metrics
        
        # Створюємо оптимізований payload
        system_prompt = self._create_expert_system_prompt(user_name)
        
        payload = {
            "model": GPT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": MAX_RESPONSE_TOKENS,
            "temperature": 0.8,
            "top_p": 0.9,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2,
            "user": str(hash(user_name))  # Для трекінгу без персональних даних
        }
        
        try:
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                
                processing_time = time.time() - start_time
                
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"🚨 OpenAI API помилка {response.status}: {error_text[:200]}")
                    
                    fallback_response = self._get_intelligent_fallback(user_name)
                    metrics = PerformanceMetrics(
                        response_time=processing_time,
                        token_count=len(fallback_response.split()),
                        success_rate=0.0
                    )
                    
                    return fallback_response, metrics
                
                result = await response.json()
                
                if "choices" not in result or not result["choices"]:
                    logger.error("🚨 Некоректна відповідь від OpenAI API")
                    
                    fallback_response = self._get_intelligent_fallback(user_name)
                    metrics = PerformanceMetrics(
                        response_time=processing_time,
                        token_count=len(fallback_response.split()),
                        success_rate=0.0
                    )
                    
                    return fallback_response, metrics
                
                gpt_response = result["choices"][0]["message"]["content"]
                cleaned_response = self._clean_and_optimize_response(gpt_response)
                
                # Зберігаємо в кеш
                self._response_cache[cache_key] = (cleaned_response, current_time)
                self._clean_cache()
                
                self.success_count += 1
                
                # Розраховуємо метрики
                metrics = PerformanceMetrics(
                    response_time=processing_time,
                    token_count=len(cleaned_response.split()),
                    success_rate=self.success_count / self.request_count
                )
                
                logger.info(f"✅ GPT відповідь для {user_name} ({processing_time:.2f}s)")
                return cleaned_response, metrics
                
        except ClientError as e:
            logger.error(f"🌐 Мережева помилка GPT: {e}")
            processing_time = time.time() - start_time
            
            fallback_response = f"Вибач, {user_name}, проблеми з з'єднанням 🌐 Спробуй через хвилину!"
            metrics = PerformanceMetrics(
                response_time=processing_time,
                token_count=len(fallback_response.split()),
                success_rate=0.0
            )
            
            return fallback_response, metrics
        
        except Exception as e:
            logger.exception(f"💥 Критична помилка GPT: {e}")
            processing_time = time.time() - start_time
            
            fallback_response = self._get_intelligent_fallback(user_name)
            metrics = PerformanceMetrics(
                response_time=processing_time,
                token_count=len(fallback_response.split()),
                success_rate=0.0
            )
            
            return fallback_response, metrics
    
    def _clean_and_optimize_response(self, response: str) -> str:
        """
        Очищує та оптимізує відповідь для найкращого UX.
        
        Args:
            response: Сира відповідь від GPT
            
        Returns:
            Очищена та оптимізована відповідь
        """
        # Видаляємо HTML теги
        response = re.sub(r"<[^>]*>", "", response)
        
        # Видаляємо markdown форматування
        response = re.sub(r"\*\*([^*]+)\*\*", r"\1", response)  # bold
        response = re.sub(r"\*([^*]+)\*", r"\1", response)      # italic
        response = re.sub(r"`([^`]+)`", r"\1", response)        # code
        response = re.sub(r"#{1,6}\s*([^\n]+)", r"\1", response)  # headers
        
        # Видаляємо згадки про версії, патчі, дати
        patterns_to_remove = [
            r"станом на.*?\d{4}",
            r"в.*?патч[іеу]?\s*\d+\.\d+",
            r"в.*?версі[іїє]?\s*\d+\.\d+",
            r"на момент.*?\d{4}",
            r"актуально.*?\d{4}",
            r"останн[іє].*?оновленн[яі]",
            r"поточн[аі].*?мет[аі]"
        ]
        
        for pattern in patterns_to_remove:
            response = re.sub(pattern, "", response, flags=re.IGNORECASE)
        
        # Очищуємо зайві пробіли та переноси
        response = re.sub(r"\n\s*\n\s*\n", "\n\n", response)
        response = re.sub(r"\s+", " ", response)
        response = response.strip()
        
        return response
    
    def _get_intelligent_fallback(self, user_name: str) -> str:
        """
        Розумна резервна відповідь залежно від контексту.
        
        Args:
            user_name: Ім'я користувача
            
        Returns:
            Персоналізована резервна відповідь
        """
        fallback_responses = [
            f"Вибач, {user_name}, зараз технічні труднощі 😔 Але я повернуся сильнішим!",
            f"Упс, {user_name}! Сервери перевантажені. Спробуй через хвилину! 🔄",
            f"{user_name}, трапилася помилка, але наша команда вже працює над фіксом! 🛠️",
            f"Не можу обробити зараз, {user_name}. Але ти можеш спробувати перефразувати запит! 💡"
        ]
        
        return fallback_responses[hash(user_name) % len(fallback_responses)]


# === ІНІЦІАЛІЗАЦІЯ БОТА ===

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# === КОМАНДИ БОТА ===

@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Революційне привітання з фокусом на стратегії замість мети.
    
    Оптимізовано для максимального engagement та UX.
    """
    try:
        user_name = message.from_user.first_name
        current_hour = datetime.now().hour
        
        # Динамічне привітання залежно від часу доби
        time_greetings = {
            range(5, 12): ("Доброго ранку", "🌅"),
            range(12, 17): ("Доброго дня", "☀️"),
            range(17, 22): ("Доброго вечора", "🌆"),
        }
        
        greeting, emoji = next(
            (greeting, emoji) for time_range, (greeting, emoji) in time_greetings.items()
            if current_hour in time_range
        ), ("Доброї ночі", "🌙")
        
        # Революційне привітання з фокусом на стратегії
        welcome_text = f"""
{greeting}, <b>{user_name}</b>! {emoji}

🎮 Вітаю в MLBB Expert Chat Bot!

Я - твій персональний про-коуч по Mobile Legends Bang Bang, готовий прокачати твої навички до рівня кіберспортсмена! 🏆

<b>💡 Як користуватися:</b>
Просто напиши своє питання після команди /go

<b>🚀 Приклади стратегічних запитів:</b>
• <code>/go соло стратегії для швидкого ранк-апу</code>
• <code>/go дуо тактики для доміну в лейті</code>
• <code>/go тріо комбо для командних боїв</code>
• <code>/go як читати карту та контролювати об'єкти</code>

<b>🎯 Мої суперсили:</b>
• Розробляю персональні стратегії
• Аналізую твій геймплей
• Навчаю читати противника
• Прокачую твою ментальність

Готовий перетворити тебе на справжнього MLBB про-гравця! 💪✨
"""
        
        await message.answer(welcome_text)
        logger.info(f"✅ Революційне привітання для {user_name}")
        
    except Exception as e:
        logger.exception(f"💥 Помилка в команді /start: {e}")
        await message.answer(
            f"Вибач, сталася помилка при завантаженні 😔\n"
            "Спробуй ще раз або використай /go для запитань!"
        )


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """
    Головна функція - революційне GPT спілкування з метриками.
    
    Оптимізовано для швидкості, якості та користувацького досвіду.
    """
    try:
        user_name = message.from_user.first_name
        user_query = message.text.replace("/go", "", 1).strip()
        
        if not user_query:
            # Розумна підказка з фокусом на стратегії
            strategy_examples = [
                "соло стратегії для кері ролі",
                "дуо синергія танк + маркс",
                "тріо ротації для контролю джанглу",
                "командні тактики для late game",
                "як покращити макро гру в ранкед"
            ]
            
            random_example = strategy_examples[hash(str(message.from_user.id)) % len(strategy_examples)]
            
            help_text = f"""
Привіт, <b>{user_name}</b>! 👋

Щоб отримати експертну відповідь, напиши свій запит після команди /go

<b>💡 Приклад:</b>
<code>/go {random_example}</code>

<b>🎯 Фокус на навичках, а не на білдах!</b>
Я допоможу тобі розвинути справжню майстерність! 🚀
"""
            
            await message.reply(help_text)
            return
        
        # Розумні індикатори обробки
        thinking_messages = [
            f"🤔 {user_name}, аналізую твою стратегію...",
            f"🧠 Готую про-поради для тебе, {user_name}!",
            f"⚡ {user_name}, розробляю тактичний план...",
            f"🎯 Шукаю найкращі рішення для тебе!",
            f"🏆 {user_name}, готую експертний аналіз..."
        ]
        
        thinking_msg = await message.reply(
            thinking_messages[hash(user_query) % len(thinking_messages)]
        )
        
        start_time = time.time()
        
        # Отримуємо експертну відповідь з метриками
        async with MLBBExpertGPT(OPENAI_API_KEY) as gpt_expert:
            response, metrics = await gpt_expert.get_expert_response(user_name, user_query)
        
        total_time = time.time() - start_time
        
        # Додаємо розширену адмін інформацію
        admin_info = ""
        if message.from_user.id == ADMIN_USER_ID:
            admin_info = (
                f"\n\n<i>⏱ Час: {total_time:.2f}с | "
                f"📊 Токени: {metrics.token_count} | "
                f"✅ Успіх: {metrics.success_rate:.1%} | "
                f"🚀 v{BOT_VERSION}</i>"
            )
        
        final_response = f"{response}{admin_info}"
        
        try:
            await thinking_msg.edit_text(final_response)
            logger.info(
                f"📤 Експертна відповідь для {user_name} "
                f"({total_time:.2f}s, {metrics.token_count} токенів)"
            )
        except TelegramBadRequest as e:
            # Якщо не можемо редагувати, відправляємо нове повідомлення
            logger.warning(f"⚠️ Не вдалося редагувати повідомлення: {e}")
            await message.reply(response)
        
    except Exception as e:
        logger.exception(f"💥 Критична помилка в команді /go: {e}")
        
        # Розумна обробка помилки
        error_response = (
            f"Вибач, {user_name if 'user_name' in locals() else 'друже'}, "
            "сталася технічна помилка 😔\n\n"
            "🔄 Спробуй:\n"
            "• Перефразувати запит\n"
            "• Повторити через хвилину\n"
            "• Використати /start для перезапуску\n\n"
            "Наша команда вже працює над фіксом! 🛠️"
        )
        
        try:
            if 'thinking_msg' in locals():
                await thinking_msg.edit_text(error_response)
            else:
                await message.reply(error_response)
        except Exception:
            # Останній резерв
            await message.reply("Технічні проблеми 😔 Спробуй пізніше!")


# === РОЗШИРЕНА ОБРОБКА ПОМИЛОК ===

@dp.errors()
async def advanced_error_handler(event, exception: Exception) -> None:
    """
    Професійний обробник помилок з детальною діагностикою.
    
    Забезпечує стабільність системи та якісний UX навіть при збоях.
    """
    error_id = int(time.time() * 1000) % 100000
    error_type = type(exception).__name__
    
    # Професійне логування з контекстом
    logger.error(
        f"🚨 Помилка #{error_id} | Тип: {error_type} | "
        f"Деталі: {str(exception)[:150]} | "
        f"Версія: {BOT_VERSION}",
        exc_info=True
    )
    
    # Розумне сповіщення адміна
    if ADMIN_USER_ID and hasattr(event, 'message') and event.message:
        try:
            user_info = "Невідомий користувач"
            if event.message.from_user:
                user_info = (
                    f"{event.message.from_user.first_name} "
                    f"(ID: {event.message.from_user.id})"
                )
            
            error_report = f"""
🚨 <b>Критична помилка #{error_id}</b>

<b>⚠️ Тип:</b> {error_type}
<b>💬 Опис:</b> {str(exception)[:250]}...
<b>👤 Користувач:</b> {user_info}
<b>🕐 Час:</b> {datetime.now().strftime('%H:%M:%S')}
<b>📝 Команда:</b> {event.message.text[:100] if event.message.text else 'N/A'}...
<b>🤖 Версія:</b> {BOT_VERSION}

<i>Автоматичне сповіщення від MLBB Expert Bot</i>
"""
            
            await bot.send_message(ADMIN_USER_ID, error_report)
            
        except Exception as notify_error:
            logger.error(f"💥 Не вдалося сповістити адміна: {notify_error}")
    
    # Розумна відповідь користувачу
    if hasattr(event, 'message') and event.message:
        try:
            user_name = "друже"
            if event.message.from_user:
                user_name = event.message.from_user.first_name
            
            # Різні типи помилок - різні відповіді
            if "timeout" in str(exception).lower():
                error_response = f"⏰ {user_name}, запит зайняв забагато часу. Спробуй простіший запит!"
            elif "rate" in str(exception).lower():
                error_response = f"🔥 {user_name}, забагато запитів! Зачекай хвилинку."
            else:
                error_response = f"""
Упс, {user_name}! Сталася технічна помилка 😔

🔍 <b>ID помилки:</b> #{error_id}
🛠️ <b>Статус:</b> Команда розробників сповіщена
⏰ <b>Час вирішення:</b> Зазвичай до години

<b>🎯 Що можеш зробити:</b>
• Повторити команду через хвилину
• Перефразувати запит простіше
• Використати /start для перезапуску

Дякую за терпіння! Ми робимо бота кращим! 🚀
"""
            
            await event.message.answer(error_response)
            
        except Exception as response_error:
            logger.error(f"💥 Не вдалося відповісти на помилку: {response_error}")


# === ФУНКЦІЇ ЖИТТЄВОГО ЦИКЛУ ===

async def startup_sequence() -> None:
    """
    Професійна послідовність запуску з валідацією та моніторингом.
    """
    logger.info(f"🚀 Запуск MLBB Expert Bot v{BOT_VERSION}...")
    
    try:
        # Валідація з'єднання з Telegram
        bot_info = await bot.get_me()
        logger.info(
            f"✅ Підключено до Telegram як @{bot_info.username} "
            f"(ID: {bot_info.id})"
        )
        
        # Сповіщення адміна з деталями
        if ADMIN_USER_ID:
            try:
                startup_message = f"""
🤖 <b>MLBB Expert Bot запущено!</b>

<b>🆔 Інформація:</b>
• Бот: @{bot_info.username}
• ID: {bot_info.id}
• Версія: {BOT_VERSION}
• Дата збірки: {BUILD_DATE}
• GPT модель: {GPT_MODEL}

<b>⏰ Час запуску:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
<b>🟢 Статус:</b> Онлайн та готовий революціонізувати MLBB спільноту!

<i>Всі системи функціонують на найвищому рівні! 🚀✨</i>
"""
                
                await bot.send_message(ADMIN_USER_ID, startup_message)
                logger.info("✅ Адміна сповіщено про успішний запуск")
                
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося сповістити адміна: {e}")
        
        # Запуск polling з оптимізованими налаштуваннями
        logger.info("🔄 Початок polling з оптимізованими налаштуваннями...")
        await dp.start_polling(
            bot, 
            skip_updates=True,  # Пропускаємо старі повідомлення
            allowed_updates=["message"]  # Обробляємо тільки повідомлення
        )
        
    except Exception as exc:
        logger.critical(f"💥 Критична помилка запуску: {exc}", exc_info=True)
        raise


async def shutdown_sequence() -> None:
    """
    Елегантна послідовність зупинки з очисткою ресурсів.
    """
    logger.info("🛑 Початок елегантної зупинки бота...")
    
    # Сповіщення адміна про зупинку
    if ADMIN_USER_ID:
        try:
            shutdown_message = f"""
🛑 <b>MLBB Expert Bot зупинено</b>

<b>⏰ Час зупинки:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
<b>🔴 Статус:</b> Офлайн
<b>📊 Версія:</b> {BOT_VERSION}

<i>Дякую за використання! До зустрічі в MLBB! 👋</i>
"""
            
            await bot.send_message(ADMIN_USER_ID, shutdown_message)
            
        except Exception as e:
            logger.warning(f"⚠️ Не вдалося сповістити про зупинку: {e}")
    
    # Коректне закриття сесії
    try:
        if bot.session:
            await bot.session.close()
        logger.info("✅ Ресурси бота коректно звільнено")
    except Exception as e:
        logger.error(f"❌ Помилка при звільненні ресурсів: {e}")
    
    logger.info("👋 Зупинка завершена успішно")


async def main() -> None:
    """
    Головна функція з професійною обробкою lifecycle.
    """
    try:
        await startup_sequence()
        
    except KeyboardInterrupt:
        logger.info("⌨️ Отримано сигнал зупинки (Ctrl+C)")
        
    except SystemExit:
        logger.info("🔄 Системний сигнал зупинки")
        
    except Exception as e:
        logger.critical(f"💥 Неочікувана критична помилка: {e}", exc_info=True)
        
    finally:
        await shutdown_sequence()


# === ТОЧКА ВХОДУ ===

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Програма завершена коректно")
    except Exception as e:
        logger.critical(f"💥 Фатальна помилка програми: {e}", exc_info=True)
