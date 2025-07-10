"""
Функції для взаємодії з базою даних (Create, Read, Update, Delete).
"""
import asyncpg
from typing import Optional, Dict, Any, Literal
from sqlalchemy import insert, update, select, delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import IntegrityError

from database.models import User
from config import ASYNC_DATABASE_URL, logger

from datetime import datetime

engine = create_async_engine(ASYNC_DATABASE_URL)

def _ensure_datetime(val):
    """
    Перетворює рядок у datetime, якщо потрібно.
    Приймає None або datetime – повертає як є.
    """
    if isinstance(val, str):
        try:
            # ISO 8601 format з +00:00
            return datetime.fromisoformat(val.replace('Z', '+00:00'))
        except Exception:
            return None
    return val

async def add_or_update_user(user_data: Dict[str, Any]) -> Literal['success', 'conflict', 'error']:
    """
    Додає або оновлює користувача, перевіряючи унікальність player_id.

    Returns:
        - 'success': Користувача успішно створено або оновлено.
        - 'conflict': Такий player_id вже зареєстрований іншим telegram_id.
        - 'error': Сталася інша помилка.
    """
    # 🧠 Уникаємо передачі рядків у поля datetime!
    for dt_field in ("created_at", "updated_at"):
        if dt_field in user_data:
            # Видаляємо, щоб БД сама проставила значення
            user_data.pop(dt_field)

    async with engine.connect() as conn:
        async with conn.begin():
            telegram_id = user_data.get('telegram_id')
            player_id = user_data.get('player_id')

            try:
                # 1. Перевіряємо, чи існує користувач з таким telegram_id
                user_by_telegram_id = await conn.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
                existing_user = user_by_telegram_id.first()

                if existing_user:
                    # Користувач з таким telegram_id вже існує - це оновлення
                    stmt = (
                        update(User)
                        .where(User.telegram_id == telegram_id)
                        .values(**user_data)
                    )
                    logger.info(f"Оновлення даних для користувача з Telegram ID: {telegram_id}")
                else:
                    # Новий користувач для цього telegram_id - це створення
                    stmt = insert(User).values(**user_data)
                    logger.info(f"Спроба створення нового користувача з Telegram ID: {telegram_id}")

                await conn.execute(stmt)
                await conn.commit()
                return 'success'

            except IntegrityError as e:
                await conn.rollback() # Відкат транзакції
                # 🧠 Більш надійна перевірка на основі тексту помилки від PostgreSQL.
                # SQLAlchemy може по-різному "загортати" вихідні помилки драйвера.
                error_text = str(e).lower()
                if 'unique constraint' in error_text and ('uq_users_player_id' in error_text or 'users_player_id_key' in error_text):
                    logger.warning(f"Конфлікт: Player ID {player_id} вже зареєстровано іншим користувачем. Спроба від Telegram ID {telegram_id}.")
                    return 'conflict'
                else:
                    logger.error(f"Неочікувана помилка цілісності: {e}", exc_info=True)
                    return 'error'
            except Exception as e:
                await conn.rollback()
                logger.error(f"Загальна помилка в add_or_update_user: {e}", exc_info=True)
                return 'error'


async def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    # ... (код функції залишається без змін) ...
    async with engine.connect() as conn:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await conn.execute(stmt)
        user_row = result.first()
        if user_row:
            # Перетворюємо результат у словник
            return dict(user_row._mapping)
    return None

async def delete_user_by_telegram_id(telegram_id: int) -> bool:
    """
    Видаляє користувача з бази даних за його Telegram ID.

    Args:
        telegram_id: Унікальний ідентифікатор користувача в Telegram.

    Returns:
        True, якщо користувача було видалено, інакше False.
    """
    async with engine.connect() as conn:
        async with conn.begin():
            stmt = delete(User).where(User.telegram_id == telegram_id)
            result = await conn.execute(stmt)
            await conn.commit()
            # result.rowcount > 0 означає, що було видалено хоча б один рядок
            if result.rowcount > 0:
                logger.info(f"Користувача з Telegram ID {telegram_id} було успішно видалено.")
                return True
            else:
                logger.warning(f"Спроба видалити несуществуючого користувача з Telegram ID {telegram_id}.")
                return False
