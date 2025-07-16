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
from typing import Any

from config import logger
from utils.redis_client import get_redis
from database.crud import get_user_by_telegram_id, add_or_update_user, get_user_settings

KEY_TEMPLATE = "cache:user:{user_id}"
CACHE_TTL = 86400  # 24 hours

_lock = asyncio.Lock()

async def load_user_cache(user_id: int) -> dict[str, Any]:
    """
    Повертає дані користувача (profile + chat_history + settings).
    Спроба завантажити з Redis; при невдачі або cache miss → із БД + кешування.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        redis = await get_redis()
        raw = await redis.get(key)
        if raw:
            logger.debug(f"Loaded user cache from Redis for user {user_id}")
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Redis unavailable on load_user_cache({user_id}): {e}")
        # При помилці Redis, переходимо до завантаження з БД
    
    # cache miss або помилка Redis → завантажуємо з БД
    logger.debug(f"Cache miss or Redis unavailable for user {user_id}. Loading from DB.")
    user_data = await get_user_by_telegram_id(user_id) or {}
    
    # ❗️ Збагачуємо кеш налаштуваннями
    settings = await get_user_settings(user_id)
    user_data['settings'] = {
        "mute_vision": settings.mute_vision,
        "mute_chat": settings.mute_chat,
        "mute_party": settings.mute_party,
    }

    if user_data:
        # Зберігаємо повний об'єкт в кеш
        await save_user_cache(user_id, user_data)
        
    return user_data

async def save_user_cache(user_id: int, user_data: dict[str, Any]) -> None:
    """
    Зберігає дані користувача в Redis з TTL та синхронно в БД (write-through).
    Якщо Redis недоступний, робить лише запис у БД.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        payload = json.dumps(user_data, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"Error serializing user_data for cache (user {user_id}): {e}", exc_info=True)
        return # Не зберігаємо пошкоджені дані

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
        # Видаляємо 'settings', оскільки вони не є частиною моделі User
        user_data_for_db = user_data.copy()
        user_data_for_db.pop('settings', None)
        
        if 'telegram_id' not in user_data_for_db:
             user_data_for_db['telegram_id'] = user_id
             
        # Перевіряємо, чи є що зберігати в основну таблицю
        if any(k in user_data_for_db for k in ['nickname', 'player_id']):
            await add_or_update_user(user_data_for_db)
            logger.debug(f"Write-through: persisted user_data to DB for user {user_id}")
    except Exception as e:
        logger.error(f"Error persisting user_data to DB for {user_id}: {e}", exc_info=True)

async def clear_user_cache(user_id: int) -> None:
    """
    Видаляє кеш користувача з Redis.
    Якщо Redis недоступний — мовчазно ігнорує.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        redis = await get_redis()
        await redis.delete(key)
        logger.info(f"Cleared user cache in Redis for user {user_id}")
    except Exception as e:
        logger.warning(f"Could not delete Redis cache for user {user_id}: {e}")
