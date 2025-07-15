"""
utils/session_memory.py

Session memory layer for unregistered users:
- Stores short-term chat history and context in Redis with TTL.
- Falls back to an in-memory store if Redis is unavailable.
- Ensures maximum history length and automatic expiration.
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from config import MAX_CHAT_HISTORY_LENGTH, logger
from utils.redis_client import get_redis

# In-memory fallback store
_in_memory_sessions: dict[int, dict[str, Any]] = {}
_in_memory_lock = asyncio.Lock()

# Session settings
SESSION_TTL: int = 3600  # 1 hour in seconds
KEY_TEMPLATE: str = "session:chat:{user_id}"


@dataclass
class SessionData:
    """Data structure for a user session."""
    chat_history: list[dict[str, Any]]
    last_activity: str
    session_context: dict[str, Any]


async def _now_iso() -> str:
    """Return current UTC time as ISO formatted string."""
    return datetime.now(timezone.utc).isoformat()


async def load_session(user_id: int) -> SessionData:
    """
    Load session for given user_id.
    Attempts Redis first, falls back to in-memory store.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        redis = await get_redis()
        raw = await redis.get(key)
        if raw:
            data = json.loads(raw)
            logger.debug(f"Loaded session from Redis for user {user_id}")
            return SessionData(**data)
    except Exception as e:
        logger.warning(f"Redis unavailable, using in-memory session for {user_id}: {e}", exc_info=True)

    # In-memory fallback
    async with _in_memory_lock:
        record = _in_memory_sessions.get(user_id)
        if record:
            logger.debug(f"Loaded session from memory for user {user_id}")
            return SessionData(**record)

    # No existing session: return new
    now = await _now_iso()
    return SessionData(chat_history=[], last_activity=now, session_context={})


async def save_session(user_id: int, session: SessionData) -> None:
    """
    Save session for given user_id.
    Persists to Redis with TTL and also updates in-memory store.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    payload = asdict(session)
    raw = json.dumps(payload, ensure_ascii=False)
    # Try Redis
    try:
        redis = await get_redis()
        await redis.set(key, raw, ex=SESSION_TTL)
        logger.debug(f"Saved session to Redis for user {user_id}")
    except Exception as e:
        logger.warning(f"Redis unavailable, using in-memory save for {user_id}: {e}", exc_info=True)

    # In-memory fallback
    async with _in_memory_lock:
        _in_memory_sessions[user_id] = payload
        logger.debug(f"Saved session to memory for user {user_id}")


async def clear_session(user_id: int) -> None:
    """
    Clear session data for given user_id.
    Removes from Redis and in-memory store.
    """
    key = KEY_TEMPLATE.format(user_id=user_id)
    try:
        redis = await get_redis()
        await redis.delete(key)
        logger.debug(f"Deleted session from Redis for user {user_id}")
    except Exception:
        logger.debug(f"No Redis session to delete for {user_id}")

    async with _in_memory_lock:
        if user_id in _in_memory_sessions:
            del _in_memory_sessions[user_id]
            logger.debug(f"Deleted session from memory for user {user_id}")


async def append_message(user_id: int, role: str, content: Any) -> None:
    """
    Append a message to the user's session history,
    enforce MAX_CHAT_HISTORY_LENGTH and update last_activity.
    """
    session = await load_session(user_id)
    entry = {"role": role, "content": content}
    session.chat_history.append(entry)
    # Trim history if exceeding maximum
    if len(session.chat_history) > MAX_CHAT_HISTORY_LENGTH:
        session.chat_history = session.chat_history[-MAX_CHAT_HISTORY_LENGTH:]

    # Update timestamp
    session.last_activity = await _now_iso()
    await save_session(user_id, session)
