"""
utils/cache_manager.py

Cache layer for registered users:
- Key: cache:user:{user_id}
- TTL: 86400 sec (24h)
- Read-through: якщо в Redis є дані → повернути їх, інакше завантажити з БД та закешувати
- Write-through: оновлює Redis + синхронно пише в БД
- Graceful fallback: якщо Redis недоступний → читати/писати безпосередньо в БД
"""

import asyncio
import json
from typing import Dict, Any, Optional

from config import logger
from utils.redis_client import get_redis
from database.crud import get_user_by_telegram_id, add_or_update_user

KEY_TEMPLATE = "cache:user:{user_id}"
CACHE_TTL = 86400  # 24 hours

_lock = asyncio.Lock()

async def load_user_cache(user_id: int) -> Dict[str, Any]:
    """
    Повертає дані користувача (profile + chat_history).
    Спроба завантажити з Redis; при невдачі або cache miss → із БД + кешування.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        redis = await get_redis()
        raw = await redis.get(key)
        if raw:
            logger.debug(f"Loaded user cache from Redis for user {user_id}")
            return json.loads(raw)
        # cache miss → load from DB and populate cache
        user_data = await get_user_by_telegram_id(user_id) or {}
        # Якщо в БД є дані, кешуємо їх
        if user_data:
            await save_user_cache(user_id, user_data)
        return user_data
    except Exception as e:
        logger.warning(f"Redis unavailable on load_user_cache({user_id}): {e}")
        user_data = await get_user_by_telegram_id(user_id) or {}
        return user_data

async def save_user_cache(user_id: int, user_data: Dict[str, Any]) -> None:
    """
    Зберігає дані користувача в Redis з TTL та синхронно в БД (write-through).
    Якщо Redis недоступний, робить лише запис у БД.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    payload = json.dumps(user_data, ensure_ascii=False)
    # Спроба запису в Redis
    try:
        redis = await get_redis()
        async with _lock:
            await redis.set(key, payload, ex=CACHE_TTL)
        logger.debug(f"Saved user cache to Redis for user {user_id}")
    except Exception as e:
        logger.warning(f"Redis unavailable on save_user_cache({user_id}): {e}")
    # Write-through: синхронний запис у БД
    try:
        # Використовуємо add_or_update_user для оновлення всіх полів, що необхідні
        user_data_copy = user_data.copy()
        user_data_copy['telegram_id'] = user_id
        await add_or_update_user(user_data_copy)
        logger.debug(f"Write-through: persisted user_data to DB for user {user_id}")
    except Exception as e:
        logger.error(f"Error persisting user_data to DB for {user_id}: {e}", exc_info=True)

async def clear_user_cache(user_id: int) -> None:
    """
    Видаляє кеш користувача з Redis. 
    При нездужанні Redis — мовчазно ігнорує.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        redis = await get_redis()
        await redis.delete(key)
        logger.debug(f"Cleared user cache in Redis for user {user_id}")
    except Exception:
        logger.debug(f"No Redis cache to delete for user {user_id}")
