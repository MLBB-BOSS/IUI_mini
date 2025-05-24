# handlers/mlbb_vision_handler.py
"""
🎮 MLBB Elite Vision Handler - Revolutionary Screenshot Analysis

Світовий рівень аналізу Mobile Legends: Bang Bang скріншотів з використанням
GPT-4 Vision API. Оптимізований для швидкості, ефективності та user experience.

Features:
- ⚡ Intelligent caching system з семантичним хешуванням
- 🧠 Adaptive prompt engineering для різних типів контенту  
- 📊 Real-time cost tracking та performance monitoring
- 🛡️ Robust error handling з exponential backoff
- 🚀 Streaming responses для покращення UX
- 💎 Enterprise-grade logging та metrics

Author: MLBB-BOSS
Version: 1.0.0
Created: 2025-05-24
Python: 3.11+
"""

import asyncio
import base64
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import wraps
from pathlib import Path
from typing import (
    Any, Dict, List, Optional, Tuple, Union, 
    Callable, Awaitable, TypeVar, Generic
)
from io import BytesIO
import json
import re

import aiohttp
import aiofiles
from PIL import Image, ImageStat
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry, stop_after_attempt, wait_exponential, 
    retry_if_exception_type, before_sleep_log
)

# Існуючі імпорти з твоєї архітектури
from config.settings import (
    OPENAI_API_KEY, VISION_MODEL_FULL, VISION_MODEL_MINI,
    VISION_MAX_TOKENS, VISION_TEMPERATURE, ADMIN_IDS, TEMP_DIR
)

# Налаштування логування з кольорами та метриками
logger = logging.getLogger(__name__)

# Глобальні константи
T = TypeVar('T')

class ContentType(Enum):
    """Типи MLBB контенту для аналізу."""
    PROFILE = auto()
    HERO_STATS = auto() 
    MATCH_RESULT = auto()
    RANK_PROGRESS = auto()
    HERO_BUILD = auto()
    TEAM_COMPOSITION = auto()
    GENERAL = auto()

class AnalysisQuality(Enum):
    """Рівні якості аналізу."""
    FAST = "fast"           # gpt-4o-mini, швидко, дешевше
    DETAILED = "detailed"   # gpt-4o, повний аналіз
    PREMIUM = "premium"     # gpt-4o + додатковий контекст

@dataclass
class VisionMetrics:
    """Метрики продуктивності Vision API."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_response_time: float = 0.0
    start_time: datetime = field(default_factory=datetime.now)
    
    @property
    def success_rate(self) -> float:
        """Розраховує відсоток успішних запитів."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def cache_hit_rate(self) -> float:
        """Розраховує відсоток попадань в кеш."""
        total_cache_requests = self.cache_hits + self.cache_misses
        if total_cache_requests == 0:
            return 0.0
        return (self.cache_hits / total_cache_requests) * 100

@dataclass
class CacheEntry:
    """Запис в кеші аналізу."""
    content_hash: str
    analysis_result: str
    metadata: Dict[str, Any]
    timestamp: datetime
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    ttl_seconds: int = 3600  # 1 година за замовчуванням
    
    @property
    def is_expired(self) -> bool:
        """Перевіряє чи застарілий запис."""
        return datetime.now() - self.timestamp > timedelta(seconds=self.ttl_seconds)
    
    def update_access(self) -> None:
        """Оновлює статистику доступу."""
        self.access_count += 1
        self.last_accessed = datetime.now()

class MLBBVisionCache:
    """
    Високопродуктивний кеш для Vision API з інтелектуальним управлінням.
    
    Features:
    - LRU eviction policy
    - TTL management
    - Content-based hashing
    - Access statistics
    """
    
    def __init__(self, max_size: int = 500, default_ttl: int = 3600):
        """
        Ініціалізує кеш з налаштуваннями.
        
        Args:
            max_size: Максимальна кількість записів
            default_ttl: TTL за замовчуванням в секундах
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._access_order: List[str] = []
        
    async def get(self, content_hash: str) -> Optional[CacheEntry]:
        """
        Отримує запис з кешу.
        
        Args:
            content_hash: Хеш контенту
            
        Returns:
            Запис кешу або None
        """
        if content_hash not in self._cache:
            return None
            
        entry = self._cache[content_hash]
        
        # Перевіряємо TTL
        if entry.is_expired:
            await self._remove_entry(content_hash)
            return None
            
        # Оновлюємо статистику доступу
        entry.update_access()
        
        # Переміщуємо в кінець (LRU)
        if content_hash in self._access_order:
            self._access_order.remove(content_hash)
        self._access_order.append(content_hash)
        
        return entry
    
    async def set(
        self, 
        content_hash: str, 
        analysis_result: str, 
        metadata: Dict[str, Any],
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Зберігає запис в кеші.
        
        Args:
            content_hash: Хеш контенту
            analysis_result: Результат аналізу
            metadata: Метадані
            ttl_seconds: TTL для цього запису
        """
        # Перевіряємо розмір кешу
        if len(self._cache) >= self._max_size:
            await self._evict_lru()
        
        # Створюємо новий запис
        entry = CacheEntry(
            content_hash=content_hash,
            analysis_result=analysis_result,
            metadata=metadata,
            timestamp=datetime.now(),
            ttl_seconds=ttl_seconds or self._default_ttl
        )
        
        self._cache[content_hash] = entry
        
        # Додаємо в порядок доступу
        if content_hash in self._access_order:
            self._access_order.remove(content_hash)
        self._access_order.append(content_hash)
    
    async def _remove_entry(self, content_hash: str) -> None:
        """Видаляє запис з кешу."""
        self._cache.pop(content_hash, None)
        if content_hash in self._access_order:
            self._access_order.remove(content_hash)
    
    async def _evict_lru(self) -> None:
        """Видаляє найменш використовуваний запис."""
        if self._access_order:
            lru_key = self._access_order[0]
            await self._remove_entry(lru_key)
    
    async def cleanup_expired(self) -> int:
        """
        Очищає застарілі записи.
        
        Returns:
            Кількість видалених записів
        """
        expired_keys = [
            key for key, entry in self._cache.items() 
            if entry.is_expired
        ]
        
        for key in expired_keys:
            await self._remove_entry(key)
            
        return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Повертає статистику кешу."""
        return {
            'size': len(self._cache),
            'max_size': self._max_size,
            'fill_percentage': (len(self._cache) / self._max_size) * 100,
            'entries': [
                {
                    'hash': entry.content_hash[:8],
                    'access_count': entry.access_count,
                    'age_seconds': (datetime.now() - entry.timestamp).total_seconds(),
                    'ttl_remaining': entry.ttl_seconds - (datetime.now() - entry.timestamp).total_seconds()
                }
                for entry in self._cache.values()
            ]
        }

class ImageProcessor:
    """
    Професійний процесор зображень для MLBB скріншотів.
    
    Оптимізує зображення для Vision API та визначає тип контенту.
    """
    
    # Розміри та формати
    MAX_DIMENSION = 2048
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    SUPPORTED_FORMATS = {'JPEG', 'PNG', 'WEBP'}
    QUALITY_SETTINGS = {
        AnalysisQuality.FAST: {'max_dim': 1024, 'quality': 75},
        AnalysisQuality.DETAILED: {'max_dim': 2048, 'quality': 85},
        AnalysisQuality.PREMIUM: {'max_dim': 2048, 'quality': 95}
    }
    
    @staticmethod
    def calculate_content_hash(image_bytes: bytes) -> str:
        """
        Розраховує семантичний хеш зображення.
        
        Враховує не тільки байти, але й візуальний контент.
        
        Args:
            image_bytes: Байти зображення
            
        Returns:
            Хеш контенту
        """
        try:
            # Базовий хеш файлу
            file_hash = hashlib.md5(image_bytes).hexdigest()
            
            # Семантичний хеш на основі статистики зображення
            with Image.open(BytesIO(image_bytes)) as img:
                # Конвертуємо в RGB
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Зменшуємо до 8x8 для семантичного хешування
                small_img = img.resize((8, 8), Image.Resampling.LANCZOS)
                
                # Розраховуємо середні значення каналів
                stat = ImageStat.Stat(small_img)
                semantic_data = f"{stat.mean}_{stat.stddev}_{img.size}"
                semantic_hash = hashlib.md5(semantic_data.encode()).hexdigest()[:8]
                
                return f"{file_hash[:16]}_{semantic_hash}"
                
        except Exception as e:
            logger.warning(f"⚠️ Помилка семантичного хешування: {e}")
            # Fallback до простого хешу
            return hashlib.md5(image_bytes).hexdigest()
    
    @staticmethod
    async def optimize_image(
        image_bytes: bytes, 
        quality: AnalysisQuality = AnalysisQuality.DETAILED
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Оптимізує зображення для Vision API.
        
        Args:
            image_bytes: Оригінальні байти
            quality: Рівень якості обробки
            
        Returns:
            Кортеж (оптимізовані байти, метадані)
        """
        start_time = time.time()
        original_size = len(image_bytes)
        
        try:
            settings = ImageProcessor.QUALITY_SETTINGS[quality]
            
            with Image.open(BytesIO(image_bytes)) as img:
                metadata = {
                    'original_size': original_size,
                    'original_dimensions': img.size,
                    'original_format': img.format,
                    'original_mode': img.mode
                }
                
                # Конвертуємо в RGB
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                elif img.mode == 'RGBA':
                    # Створюємо білий фон для RGBA
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                
                # Обертаємо за EXIF
                img = ImageProcessor._apply_exif_rotation(img)
                
                # Зменшуємо розмір якщо потрібно
                if max(img.size) > settings['max_dim']:
                    ratio = settings['max_dim'] / max(img.size)
                    new_size = tuple(int(dim * ratio) for dim in img.size)
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    logger.debug(f"🔧 Зображення змінено: {img.size}")
                
                # Зберігаємо оптимізоване
                output = BytesIO()
                img.save(
                    output, 
                    format='JPEG', 
                    quality=settings['quality'], 
                    optimize=True,
                    progressive=True
                )
                
                optimized_bytes = output.getvalue()
                
                # Оновлюємо метадані
                metadata.update({
                    'optimized_size': len(optimized_bytes),
                    'optimized_dimensions': img.size,
                    'compression_ratio': original_size / len(optimized_bytes),
                    'processing_time': time.time() - start_time,
                    'quality_level': quality.value
                })
                
                logger.debug(
                    f"📸 Оптимізація: {original_size} → {len(optimized_bytes)} байт "
                    f"({metadata['compression_ratio']:.1f}x, {metadata['processing_time']:.2f}s)"
                )
                
                return optimized_bytes, metadata
                
        except Exception as e:
            logger.error(f"❌ Помилка оптимізації зображення: {e}")
            # Повертаємо оригінал з базовими метаданими
            return image_bytes, {
                'original_size': original_size,
                'optimization_failed': True,
                'error': str(e)
            }
    
    @staticmethod
    def _apply_exif_rotation(img: Image.Image) -> Image.Image:
        """Застосовує EXIF ротацію до зображення."""
        try:
            exif = img._getexif()
            if exif is not None:
                orientation = exif.get(274)  # EXIF Orientation tag
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except (AttributeError, KeyError, TypeError):
            pass  # Немає EXIF або помилка
        return img
    
    @staticmethod
    def detect_content_type(image_bytes: bytes) -> ContentType:
        """
        Визначає тип MLBB контенту на зображенні.
        
        Використовує комп'ютерний зір для класифікації.
        
        Args:
            image_bytes: Байти зображення
            
        Returns:
            Визначений тип контенту
        """
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                # Конвертуємо в RGB для аналізу
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Зменшуємо для швидкого аналізу
                small_img = img.resize((224, 224), Image.Resampling.LANCZOS)
                
                # Аналіз кольорової палітри
                stat = ImageStat.Stat(small_img)
                avg_brightness = sum(stat.mean) / 3
                
                # Аналіз співвідношення сторін
                aspect_ratio = img.width / img.height
                
                # Евристичний аналіз (в майбутньому - ML модель)
                if 0.45 <= aspect_ratio <= 0.55:  # Квадратиші - профіль
                    return ContentType.PROFILE
                elif aspect_ratio > 1.5:  # Широкі - результат матчу
                    return ContentType.MATCH_RESULT
                elif avg_brightness > 150:  # Світлі - статистика
                    return ContentType.HERO_STATS
                else:
                    return ContentType.GENERAL
                    
        except Exception as e:
            logger.warning(f"⚠️ Помилка визначення типу контенту: {e}")
            return ContentType.GENERAL

class PromptEngine:
    """
    Інтелектуальний генератор промптів для різних типів MLBB контенту.
    
    Використовує адаптивні промпти залежно від контексту та якості аналізу.
    """
    
    # Базові промпти для різних типів контенту
    BASE_PROMPTS = {
        ContentType.PROFILE: """
🎮 **MLBB Profile Expert Analysis**

Ти провідний аналітик Mobile Legends: Bang Bang з 7+ років досвіду в кіберспорті.

📋 **ЗАВДАННЯ**: Проведи експертний аналіз профілю гравця MLBB та надай професійні рекомендації українською мовою.

📊 **СТРУКТУРА АНАЛІЗУ**:

👤 **ПРОФІЛЬ ГРАВЦЯ**
- Username та MLBB ID (якщо видно)
- Поточний ранг та сезонний прогрес
- Загальна статистика матчів та WinRate
- Рівень акаунту та досягнення

⭐ **ОЦІНКА ПРОГРЕСУ**
- Аналіз сильних сторін гравця
- Виявлення областей для покращення  
- Оцінка потенціалу зростання
- Порівняння з середніми показниками

🎯 **ПЕРСОНАЛЬНІ РЕКОМЕНДАЦІЇ**
- Короткострокові цілі (1-2 тижні)
- Середньострокові цілі (місяць)
- Довгострокові цілі (сезон)
- Рекомендовані ролі та герої

📈 **СТРАТЕГІЧНИЙ ПЛАН**
- Реалістичний прогноз рангу до кінця сезону
- Конкретні кроки для досягнення цілей
- Рекомендації по стилю гри

🔍 **ТЕХНІЧНІ ДЕТАЛІ**
Будь максимально конкретним у рекомендаціях. Використовуй емодзі, markdown та структурований формат. Мотивуй гравця та надавай конструктивну критику.
""",
        
        ContentType.HERO_STATS: """
🦸 **MLBB Hero Performance Analysis**

Ти експерт з героїв Mobile Legends: Bang Bang та професійний coach.

📋 **ЗАВДАННЯ**: Проаналізуй статистику героя та надай експертні рекомендації для покращення performance українською мовою.

📊 **СТРУКТУРА АНАЛІЗУ**:

🦸 **СТАТИСТИКА ГЕРОЯ**
- Назва героя, роль та позиція в меті
- Кількість матчів та WinRate з героєм
- KDA співвідношення та детальна статистика
- Рівень майстерності та досвід

💎 **АНАЛІЗ ЕФЕКТИВНОСТІ**
- Оцінка поточної продуктивності
- Порівняння з середніми показниками по ролі
- Сильні та слабкі аспекти геймплею
- Аналіз consistency performance

⚔️ **ГЕЙМПЛЕЙ РЕКОМЕНДАЦІЇ**
- Оптимальний білд (предмети) для різних ситуацій
- Рекомендовані емблеми та налаштування
- Тактика на різних фазах гри
- Позиціонування та ротації

🎯 **ПЛАН УДОСКОНАЛЕННЯ**
- Конкретні навички для відпрацювання
- Ігрові ситуації для вивчення
- Цілі по статистиці на наступний місяць
- Контр-піки та синергії в команді

🔍 **МЕТА-АНАЛІЗ**
Враховуй поточний стан балансу героя, популярність в ранкед іграх та ефективність на різних рангах.
""",
        
        ContentType.MATCH_RESULT: """
⚔️ **MLBB Match Performance Analysis**

Ти професійний аналітик кіберспортивних матчів MLBB та coach високого рівня.

📋 **ЗАВДАННЯ**: Проведи детальний розбір матчу та надай професійні insights українською мовою.

📊 **СТРУКТУРА АНАЛІЗУ**:

🏆 **РЕЗУЛЬТАТ МАТЧУ**
- Результат (Victory/Defeat) та загальні показники
- Тривалість гри та динаміка матчу
- Режим гри (Ranked/Classic/Draft) та карта

👥 **КОМАНДНИЙ АНАЛІЗ**
- Композиція команд та синергія ролей
- Ключові teamfights та turning points
- Контроль об'єктів (Lord, Turtle, Towers)
- MVP та слабка ланка команди

🎮 **ІНДИВІДУАЛЬНА ПРОДУКТИВНІСТЬ**
- Детальна KDA та participation rate
- Фарм ефективність та економіка
- Urон по типах (Hero/Turret/Total)
- Оцінка білдів та item choices

💡 **СТРАТЕГІЧНІ ВИСНОВКИ**
- Що було зроблено правильно
- Критичні помилки та missed opportunities  
- Рекомендації для схожих матчів
- Lessons learned для майбутнього

🔍 **ТАКТИЧНИЙ АНАЛІЗ**
Фокусуйся на конкретних моментах які можна покращити. Надавай actionable advice для зростання skill level.
""",
        
        ContentType.GENERAL: """
🎮 **MLBB Universal Expert Analysis**

Ти універсальний експерт Mobile Legends: Bang Bang з глибоким розумінням всіх аспектів гри.

📋 **ЗАВДАННЯ**: Проаналізуй MLBB скріншот та надай максимально корисну інформацію українською мовою.

📊 **ПРИНЦИПИ АНАЛІЗУ**:
✅ Спочатку визнач тип контенту (профіль, статистика, матч, білд, тощо)
✅ Надай структурований аналіз з емодзі та markdown
✅ Будь конкретним та actionable у порадах  
✅ Використовуй професійну MLBB термінологію
✅ Мотивуй гравця до покращення

🎯 **ОБОВ'ЯЗКОВО ВКЛЮЧАЙ**:
- Чіткий опис того, що зображено
- Ключові показники та цифри
- Виявлені сильні сторони
- Конкретні рекомендації для покращення
- Наступні кроки та цілі

🔍 **ЕКСПЕРТНИЙ ПІДХІД**
Будь ментором який справді допомагає гравцям стати кращими. Надавай insights які неможливо отримати без експертного досвіду.
"""
    }
    
    # Модифікатори для різних рівнів якості
    QUALITY_MODIFIERS = {
        AnalysisQuality.FAST: "\n\n⚡ **ШВИДКИЙ АНАЛІЗ**: Надай стислі, але корисні рекомендації. Фокусуйся на найголовніших моментах.",
        
        AnalysisQuality.DETAILED: "\n\n📊 **ДЕТАЛЬНИЙ АНАЛІЗ**: Проведи глибокий розбір з конкретними числами та детальними рекомендаціями.",
        
        AnalysisQuality.PREMIUM: "\n\n💎 **ПРЕМІУМ АНАЛІЗ**: Максимально детальний експертний розбір з прогнозами, стратегічними insights та персоналізованими рекомендаціями на основі мета-гри."
    }
    
    @classmethod
    def generate_prompt(
        cls, 
        content_type: ContentType, 
        quality: AnalysisQuality = AnalysisQuality.DETAILED,
        user_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Генерує адаптивний промпт для аналізу.
        
        Args:
            content_type: Тип контенту
            quality: Рівень якості аналізу
            user_context: Додатковий контекст користувача
            
        Returns:
            Оптимізований промпт
        """
        base_prompt = cls.BASE_PROMPTS.get(content_type, cls.BASE_PROMPTS[ContentType.GENERAL])
        quality_modifier = cls.QUALITY_MODIFIERS.get(quality, "")
        
        prompt = base_prompt + quality_modifier
        
        # Додаємо контекст користувача якщо є
        if user_context:
            context_additions = []
            
            if user_context.get('user_rank'):
                context_additions.append(f"🏆 Ранг користувача: {user_context['user_rank']}")
                
            if user_context.get('main_role'):
                context_additions.append(f"🎭 Основна роль: {user_context['main_role']}")
                
            if user_context.get('favorite_heroes'):
                heroes = ', '.join(user_context['favorite_heroes'])
                context_additions.append(f"⭐ Улюблені герої: {heroes}")
            
            if context_additions:
                prompt += f"\n\n🎯 **КОНТЕКСТ КОРИСТУВАЧА**:\n" + "\n".join(context_additions)
        
        return prompt

def performance_monitor(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """
    Декоратор для моніторингу продуктивності асинхронних функцій.
    
    Args:
        func: Функція для моніторингу
        
    Returns:
        Обгорнута функція з моніторингом
    """
    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        start_time = time.time()
        func_name = func.__name__
        
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            logger.debug(f"⚡ {func_name} виконано за {execution_time:.3f}s")
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"❌ {func_name} помилка за {execution_time:.3f}s: {e}")
            raise
            
    return wrapper

class MLBBVisionAnalyzer:
    """
    Революційний аналізатор MLBB скріншотів світового рівня.
    
    Features:
    - 🧠 Intelligent content detection
    - ⚡ High-performance caching  
    - 📊 Real-time metrics tracking
    - 🛡️ Enterprise error handling
    - 💎 Adaptive quality control
    """
    
    def __init__(self):
        """Ініціалізує аналізатор з усіма компонентами."""
        self.cache = MLBBVisionCache(max_size=1000, default_ttl=7200)  # 2 години
        self.metrics = VisionMetrics()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting
        self._last_request_time = 0.0
        self._min_request_interval = 0.1  # 100ms між запитами
        
    async def __aenter__(self):
        """Async context manager вхід."""
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(
            total=120,  # Загальний таймаут
            connect=10,  # Таймаут підключення  
            sock_read=60  # Таймаут читання
        )
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'User-Agent': 'MLBB-Vision-Bot/1.0'
            }
        )
        
        logger.info("🚀 MLBBVisionAnalyzer ініціалізовано")
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager вихід."""
        if self.session:
            await self.session.close()
        
        # Очищуємо застарілий кеш
        expired_count = await self.cache.cleanup_expired()
        if expired_count > 0:
            logger.info(f"🧹 Очищено {expired_count} застарілих записів кешу")
    
    @performance_monitor
    async def analyze_screenshot(
        self,
        image_bytes: bytes,
        quality: AnalysisQuality = AnalysisQuality.DETAILED,
        user_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Аналізує MLBB скріншот з максимальною ефективністю.
        
        Args:
            image_bytes: Байти зображення
            quality: Рівень якості аналізу
            user_context: Контекст користувача
            
        Returns:
            Кортеж (результат аналізу, метадані)
            
        Raises:
            ValueError: Неправильний формат зображення
            aiohttp.ClientError: Помилка API
        """
        analysis_start = time.time()
        
        try:
            # Генеруємо хеш контенту
            content_hash = ImageProcessor.calculate_content_hash(image_bytes)
            
            # Перевіряємо кеш
            cache_key = f"{quality.value}_{content_hash}"
            cached_entry = await self.cache.get(cache_key)
            
            if cached_entry:
                self.metrics.cache_hits += 1
                logger.info(f"🎯 Кеш HIT для {content_hash[:8]}")
                
                return cached_entry.analysis_result, {
                    **cached_entry.metadata,
                    'cache_hit': True,
                    'cache_access_count': cached_entry.access_count
                }
            
            self.metrics.cache_misses += 1
            
            # Визначаємо тип контенту
            content_type = ImageProcessor.detect_content_type(image_bytes)
            
            # Оптимізуємо зображення
            optimized_bytes, optimization_meta = await ImageProcessor.optimize_image(
                image_bytes, quality
            )
            
            # Генеруємо промпт
            prompt = PromptEngine.generate_prompt(content_type, quality, user_context)
            
            # Викликаємо OpenAI API
            analysis_result, api_metadata = await self._call_openai_vision(
                optimized_bytes, prompt, quality
            )
            
            # Формуємо повні метадані
            full_metadata = {
                'content_type': content_type.name.lower(),
                'quality_level': quality.value,
                'content_hash': content_hash,
                'analysis_time': time.time() - analysis_start,
                'cache_hit': False,
                **optimization_meta,
                **api_metadata
            }
            
            # Зберігаємо в кеш
            cache_ttl = self._calculate_cache_ttl(quality, api_metadata)
            await self.cache.set(cache_key, analysis_result, full_metadata, cache_ttl)
            
            # Оновлюємо метрики
            self.metrics.total_requests += 1
            self.metrics.successful_requests += 1
            self.metrics.total_tokens += api_metadata.get('tokens_used', 0)
            
            # Розраховуємо вартість
            cost = self._calculate_cost(api_metadata.get('model'), api_metadata.get('tokens_used', 0))
            self.metrics.total_cost_usd += cost
            full_metadata['estimated_cost_usd'] = cost
            
            logger.info(
                f"✅ Аналіз завершено: {content_type.name} за {full_metadata['analysis_time']:.2f}s, "
                f"токени: {api_metadata.get('tokens_used', 0)}, вартість: ${cost:.4f}"
            )
            
            return analysis_result, full_metadata
            
        except Exception as e:
            self.metrics.total_requests += 1
            self.metrics.failed_requests += 1
            
            logger.error(f"❌ Помилка аналізу: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def _call_openai_vision(
        self,
        image_bytes: bytes,
        prompt: str,
        quality: AnalysisQuality
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Викликає OpenAI Vision API з retry та rate limiting.
        
        Args:
            image_bytes: Оптимізовані байти зображення
            prompt: Промпт для аналізу
            quality: Рівень якості
            
        Returns:
            Кортеж (результат, метадані API)
        """
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        
        self._last_request_time = time.time()
        
        # Вибираємо модель залежно від якості
        model = VISION_MODEL_FULL if quality in (AnalysisQuality.DETAILED, AnalysisQuality.PREMIUM) else VISION_MODEL_MINI
        
        # Кодуємо зображення
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # Формуємо запит
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high" if quality == AnalysisQuality.PREMIUM else "auto"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": VISION_MAX_TOKENS,
            "temperature": VISION_TEMPERATURE
        }
        
        logger.debug(f"🤖 API запит: модель={model}, якість={quality.value}")
        
        # Викликаємо API
        async with self.session.post(
            'https://api.openai.com/v1/chat/completions',
            json=payload
        ) as response:
            
            if response.status == 429:  # Rate limit
                retry_after = int(response.headers.get('retry-after', 60))
                logger.warning(f"⏱ Rate limit, чекаємо {retry_after}s")
                await asyncio.sleep(retry_after)
                raise aiohttp.ClientError("Rate limit exceeded")
            
            response.raise_for_status()
            data = await response.json()
            
            # Парсимо відповідь
            result = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            
            metadata = {
                'model': data.get('model', model),
                'tokens_used': usage.get('total_tokens', 0),
                'prompt_tokens': usage.get('prompt_tokens', 0),
                'completion_tokens': usage.get('completion_tokens', 0),
                'finish_reason': data['choices'][0].get('finish_reason'),
                'response_time': time.time() - self._last_request_time
            }
            
            return result, metadata
    
    @staticmethod
    def _calculate_cost(model: str, tokens: int) -> float:
        """
        Розраховує приблизну вартість API виклику.
        
        Args:
            model: Назва моделі
            tokens: Кількість токенів
            
        Returns:
            Вартість в USD
        """
        # Ціни станом на 2024 (за 1K токенів)
        pricing = {
            'gpt-4o': 0.005,  # $5/1M tokens
            'gpt-4o-mini': 0.00015,  # $0.15/1M tokens
            'gpt-4-vision-preview': 0.01,  # Legacy
        }
        
        rate = pricing.get(model, 0.005)  # Default to gpt-4o rate
        return (tokens / 1000) * rate
    
    @staticmethod  
    def _calculate_cache_ttl(quality: AnalysisQuality, metadata: Dict[str, Any]) -> int:
        """
        Розраховує TTL для кешу залежно від якості та результату.
        
        Args:
            quality: Рівень якості аналізу
            metadata: Метадані API відповіді
            
        Returns:
            TTL в секундах
        """
        base_ttl = {
            AnalysisQuality.FAST: 1800,      # 30 хвилин
            AnalysisQuality.DETAILED: 7200,  # 2 години  
            AnalysisQuality.PREMIUM: 14400   # 4 години
        }
        
        ttl = base_ttl.get(quality, 3600)
        
        # Збільшуємо TTL для якісних результатів
        if metadata.get('tokens_used', 0) > 1000:
            ttl *= 1.5
            
        return int(ttl)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Повертає поточні метрики аналізатора."""
        cache_stats = self.cache.get_stats()
        
        return {
            'api_metrics': {
                'total_requests': self.metrics.total_requests,
                'successful_requests': self.metrics.successful_requests,
                'failed_requests': self.metrics.failed_requests,
                'success_rate': self.metrics.success_rate,
                'total_tokens': self.metrics.total_tokens,
                'total_cost_usd': round(self.metrics.total_cost_usd, 4),
                'uptime_seconds': (datetime.now() - self.metrics.start_time).total_seconds()
            },
            'cache_metrics': {
                'hits': self.metrics.cache_hits,
                'misses': self.metrics.cache_misses,
                'hit_rate': self.metrics.cache_hit_rate,
                **cache_stats
            }
        }

# Глобальний екземпляр для використання в handlers
_global_analyzer: Optional[MLBBVisionAnalyzer] = None

async def get_analyzer() -> MLBBVisionAnalyzer:
    """
    Отримує глобальний екземпляр аналізатора.
    
    Returns:
        Ініціалізований аналізатор
    """
    global _global_analyzer
    
    if _global_analyzer is None:
        _global_analyzer = MLBBVisionAnalyzer()
    
    return _global_analyzer

# Ініціалізуємо роутер
vision_router = Router(name="mlbb_vision_handler")

# === HANDLERS ===

@vision_router.message(F.photo)
async def handle_vision_photo(
    message: Message,
    state: FSMContext, 
    session: AsyncSession
) -> None:
    """
    Революційний обробник фотографій з MLBB Vision аналізом.
    
    Args:
        message: Повідомлення з фото
        state: FSM стан
        session: Сесія БД
    """
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    logger.info(f"📸 Vision запит від {user_id} (@{username})")
    
    # Початкове повідомлення з прогресом
    progress_msg = await message.reply(
        "🔍 <b>MLBB Vision Analysis</b>\n\n"
        "📸 Завантажую зображення...\n"
        "⏱ Приблизний час: 15-45 секунд\n\n"
        "<i>Використовую GPT-4 Vision для професійного аналізу</i>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Отримуємо найбільше фото
        photo = message.photo[-1]
        
        # Перевіряємо розмір
        if photo.file_size and photo.file_size > ImageProcessor.MAX_FILE_SIZE:
            size_mb = photo.file_size / (1024 * 1024)
            await progress_msg.edit_text(
                f"❌ <b>Файл занадто великий</b>\n\n"
                f"📊 Поточний розмір: {size_mb:.1f}MB\n"
                f"📏 Максимум: {ImageProcessor.MAX_FILE_SIZE // (1024 * 1024)}MB\n\n"
                f"💡 Стисни зображення та спробуй ще раз",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Оновлюємо прогрес
        await progress_msg.edit_text(
            "🔍 <b>MLBB Vision Analysis</b>\n\n"
            "⬇️ Завантажую файл...\n"
            "🤖 Підготовка до аналізу\n\n"
            "<i>Оптимізую зображення для AI</i>",
            parse_mode=ParseMode.HTML
        )
        
        # Завантажуємо файл
        file = await message.bot.get_file(photo.file_id)
        file_data = await message.bot.download_file(file.file_path)
        image_bytes = file_data.read()
        
        logger.info(f"⬇️ Завантажено: {len(image_bytes)} байт від {user_id}")
        
        # Оновлюємо прогрес  
        await progress_msg.edit_text(
            "🔍 <b>MLBB Vision Analysis</b>\n\n"
            "🧠 Аналізую за допомогою GPT-4 Vision...\n"
            "🎮 Визначаю тип MLBB контенту\n\n"
            "<i>Генерую професійні рекомендації</i>",
            parse_mode=ParseMode.HTML
        )
        
        # Отримуємо контекст користувача (можна розширити пізніше)
        user_context = {
            'user_id': user_id,
            'username': username
            # TODO: Додати інформацію з БД про користувача
        }
        
        # Виконуємо аналіз
        async with MLBBVisionAnalyzer() as analyzer:
            analysis_result, metadata = await analyzer.analyze_screenshot(
                image_bytes=image_bytes,
                quality=AnalysisQuality.DETAILED,
                user_context=user_context
            )
        
        # Форматуємо результат
        formatted_response = (
            f"🎮 <b>MLBB Expert Analysis</b>\n\n"
            f"{analysis_result}\n\n"
            f"<i>🤖 Модель: {metadata.get('model', 'gpt-4o')}\n"
            f"⚡ Токени: {metadata.get('tokens_used', 0)}\n"
            f"💰 Вартість: ${metadata.get('estimated_cost_usd', 0):.4f}\n"
            f"⏱ Час аналізу: {metadata.get('analysis_time', 0):.1f}s</i>"
        )
        
        # Відправляємо результат (можливо кілька повідомлень)
        await _send_long_message(message, progress_msg, formatted_response)
        
        logger.info(
            f"✅ Vision аналіз завершено для {user_id}: "
            f"{metadata.get('content_type')} за {metadata.get('analysis_time', 0):.1f}s"
        )
        
    except Exception as e:
        logger.error(f"❌ Помилка Vision аналізу для {user_id}: {e}")
        
        error_message = (
            "❌ <b>Помилка аналізу</b>\n\n"
            "Вибач, сталася помилка під час обробки зображення.\n\n"
            "💡 <b>Рекомендації:</b>\n"
            "• Переконайся що зображення чітке\n"
            "• Розмір не більше 20MB\n"
            "• Формат: JPG, PNG або WebP\n"
            "• Спробуй інший скріншот\n\n"
            "<i>Якщо проблема повторюється - повідом адміна</i>"
        )
        
        try:
            await progress_msg.edit_text(error_message, parse_mode=ParseMode.HTML)
        except:
            await message.reply(error_message, parse_mode=ParseMode.HTML)

async def _send_long_message(
    original_message: Message,
    progress_message: Message, 
    content: str,
    max_length: int = 4096
) -> None:
    """
    Відправляє довгий контент, розбиваючи на частини якщо потрібно.
    
    Args:
        original_message: Оригінальне повідомлення
        progress_message: Повідомлення прогресу для редагування
        content: Контент для відправки
        max_length: Максимальна довжина повідомлення
    """
    if len(content) <= max_length:
        try:
            await progress_message.edit_text(content, parse_mode=ParseMode.HTML)
        except TelegramBadRequest:
            # Fallback - відправляємо як нове повідомлення
            await progress_message.delete()
            await original_message.reply(content, parse_mode=ParseMode.HTML)
    else:
        # Розбиваємо на частини
        await progress_message.edit_text(
            "🎮 <b>MLBB Expert Analysis</b>\n\n"
            "<i>Результат занадто довгий, відправляю частинами...</i>",
            parse_mode=ParseMode.HTML
        )
        
        # Розумно розбиваємо текст
        parts = _split_text_smart(content, max_length - 100)  # Залишаємо місце для заголовків
        
        for i, part in enumerate(parts, 1):
            formatted_part = f"<b>Частина {i}/{len(parts)}:</b>\n\n{part}"
            await original_message.reply(formatted_part, parse_mode=ParseMode.HTML)
            
            # Невелика затримка між повідомленнями
            if i < len(parts):
                await asyncio.sleep(0.5)

def _split_text_smart(text: str, max_length: int) -> List[str]:
    """
    Розумно розбиває текст на частини, зберігаючи структуру.
    
    Args:
        text: Текст для розбиття
        max_length: Максимальна довжина частини
        
    Returns:
        Список частин тексту
    """
    if len(text) <= max_length:
        return [text]
    
    parts = []
    current_part = ""
    
    # Розбиваємо по параграфах
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # Якщо параграф сам по собі завеликий
        if len(paragraph) > max_length:
            # Розбиваємо по реченнях
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            
            for sentence in sentences:
                if len(current_part + sentence) > max_length:
                    if current_part:
                        parts.append(current_part.strip())
                        current_part = sentence
                    else:
                        # Речення завелике - розбиваємо примусово
                        while len(sentence) > max_length:
                            parts.append(sentence[:max_length].strip())
                            sentence = sentence[max_length:]
                        current_part = sentence
                else:
                    current_part += sentence + " "
        else:
            if len(current_part + paragraph) > max_length:
                if current_part:
                    parts.append(current_part.strip())
                    current_part = paragraph + "\n\n"
                else:
                    current_part = paragraph + "\n\n"
            else:
                current_part += paragraph + "\n\n"
    
    if current_part.strip():
        parts.append(current_part.strip())
    
    return parts

# === ADMIN COMMANDS ===

@vision_router.message(F.text == "/vision_stats", F.from_user.id.in_(ADMIN_IDS))
async def show_vision_statistics(message: Message) -> None:
    """
    Показує детальну статистику Vision системи для адміністраторів.
    
    Args:
        message: Повідомлення команди
    """
    try:
        analyzer = await get_analyzer()
        metrics = analyzer.get_metrics()
        
        api_metrics = metrics['api_metrics']
        cache_metrics = metrics['cache_metrics']
        
        # Форматуємо uptime
        uptime_seconds = api_metrics['uptime_seconds']
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        
        stats_text = f"""
📊 <b>MLBB Vision Statistics</b>

🤖 <b>API Metrics:</b>
• Всього запитів: {api_metrics['total_requests']}
• Успішні: {api_metrics['successful_requests']}  
• Помилки: {api_metrics['failed_requests']}
• Success Rate: {api_metrics['success_rate']:.1f}%
• Токени: {api_metrics['total_tokens']:,}
• Вартість: ${api_metrics['total_cost_usd']:.4f}

💾 <b>Cache Metrics:</b>
• Хіти: {cache_metrics['hits']}
• Промахи: {cache_metrics['misses']}
• Hit Rate: {cache_metrics['hit_rate']:.1f}%
• Розмір кешу: {cache_metrics['size']}/{cache_metrics['max_size']}
• Заповненість: {cache_metrics['fill_percentage']:.1f}%

⏱ <b>Uptime:</b> {uptime_str}

<i>Останнє оновлення: {datetime.now().strftime('%H:%M:%S')}</i>
"""
        
        await message.reply(stats_text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"❌ Помилка отримання статистики: {e}")
        await message.reply("❌ Помилка отримання статистики")

@vision_router.message(F.text == "/vision_cache_clear", F.from_user.id.in_(ADMIN_IDS))
async def clear_vision_cache_command(message: Message) -> None:
    """
    Очищує кеш Vision системи.
    
    Args:
        message: Повідомлення команди
    """
    try:
        analyzer = await get_analyzer()
        
        # Отримуємо статистику до очищення
        old_stats = analyzer.cache.get_stats()
        old_size = old_stats['size']
        
        # Очищуємо кеш
        analyzer.cache._cache.clear()
        analyzer.cache._access_order.clear()
        
        await message.reply(
            f"✅ <b>Кеш очищено</b>\n\n"
            f"Видалено записів: {old_size}\n"
            f"Звільнено пам'яті: ~{old_size * 2}KB",
            parse_mode=ParseMode.HTML
        )
        
        logger.info(f"🧹 Кеш очищено адміністратором {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"❌ Помилка очищення кешу: {e}")
        await message.reply("❌ Помилка очищення кешу")

# === INTEGRATION FUNCTIONS ===

def get_vision_router() -> Router:
    """
    Повертає налаштований Vision роутер для інтеграції.
    
    Returns:
        Готовий роутер
    """
    return vision_router

async def get_vision_metrics() -> Dict[str, Any]:
    """
    Повертає метрики Vision системи для інтеграції.
    
    Returns:
        Словник з метриками
    """
    try:
        analyzer = await get_analyzer()
        return analyzer.get_metrics()
    except Exception as e:
        logger.error(f"❌ Помилка отримання метрик: {e}")
        return {}

# === STARTUP TASKS ===

async def initialize_vision_system() -> None:
    """
    Ініціалізує Vision систему при старті бота.
    """
    try:
        # Створюємо директорії якщо потрібно
        temp_path = Path(TEMP_DIR)
        temp_path.mkdir(parents=True, exist_ok=True)
        
        # Перевіряємо наявність API ключа
        if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_OPENAI_API_KEY":
            logger.warning("⚠️ OPENAI_API_KEY не налаштований!")
            return
        
        # Ініціалізуємо глобальний аналізатор
        global _global_analyzer
        _global_analyzer = MLBBVisionAnalyzer()
        
        logger.info("🚀 MLBB Vision System ініціалізовано успішно")
        
    except Exception as e:
        logger.error(f"❌ Помилка ініціалізації Vision системи: {e}")

# === CLEANUP TASKS ===

async def cleanup_vision_system() -> None:
    """
    Очищає ресурси Vision системи при зупинці бота.
    """
    try:
        global _global_analyzer
        
        if _global_analyzer:
            # Очищуємо застарілий кеш
            expired_count = await _global_analyzer.cache.cleanup_expired()
            
            # Логуємо фінальну статистику
            metrics = _global_analyzer.get_metrics()
            api_metrics = metrics['api_metrics']
            
            logger.info(
                f"📊 Vision система зупинена: "
                f"{api_metrics['total_requests']} запитів, "
                f"${api_metrics['total_cost_usd']:.4f} вартість, "
                f"{expired_count} записів очищено"
            )
            
            _global_analyzer = None
        
        logger.info("👋 MLBB Vision System завершено")
        
    except Exception as e:
        
