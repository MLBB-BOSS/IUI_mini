"""
utils/redis_client.py

Асинхронний менеджер з’єднань до Redis через офіційний redis-py (asyncio).
"""
import asyncio
from typing import Optional

from redis import asyncio as aioredis  # ← замість окремого aioredis
from config import REDIS_URL, logger

_redis: Optional[aioredis.Redis] = None
_lock = asyncio.Lock()

async def get_redis() -> aioredis.Redis:
    """
    Повертає глобальний пул з’єднань Redis.
    Ініціалізується при першому виклику.
    """
    global _redis
    if _redis is None:
        async with _lock:
            if _redis is None:
                if not REDIS_URL:
                    raise RuntimeError("REDIS_URL is not set in config.")
                try:
                    # Використовуємо redis-py asyncio API
                    _redis = aioredis.from_url(
                        REDIS_URL, encoding="utf-8", decode_responses=True, max_connections=10
                    )
                    logger.info("✅ Redis (redis-py asyncio) client initialized.")
                except Exception as e:
                    logger.error(f"❌ Failed to connect to Redis: {e}", exc_info=True)
                    raise
    return _redis

async def close_redis() -> None:
    """
    Закриває з’єднання Redis при завершенні програми.
    """
    global _redis
    if _redis:
        try:
            await _redis.close()
            logger.info("🔒 Redis connection closed.")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}", exc_info=True)
        finally:
            _redis = None
