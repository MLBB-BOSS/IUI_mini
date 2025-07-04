"""
Функції для взаємодії з базою даних (Create, Read, Update, Delete).
"""
import asyncpg
from typing import Optional, Dict, Any
from sqlalchemy import insert, update, select, delete
from sqlalchemy.ext.asyncio import create_async_engine

from database.models import User
# 🆕 Використовуємо ASYNC_DATABASE_URL для всіх операцій у боті
from config import ASYNC_DATABASE_URL, logger

# 🆕 Створюємо асинхронний двигун з правильного URL
engine = create_async_engine(ASYNC_DATABASE_URL)

async def add_or_update_user(user_data: Dict[str, Any]) -> None:
    # ... (код функції залишається без змін) ...
    async with engine.connect() as conn:
        async with conn.begin(): # Починаємо транзакцію
            # Перевіряємо, чи існує користувач
            user_exists_stmt = select(User.telegram_id).where(User.telegram_id == user_data['telegram_id'])
            existing_user = await conn.execute(user_exists_stmt)
            
            if existing_user.scalar_one_or_none() is not None:
                # Оновлюємо існуючого користувача
                stmt = (
                    update(User)
                    .where(User.telegram_id == user_data['telegram_id'])
                    .values(**user_data)
                )
                logger.info(f"Оновлення даних для користувача з Telegram ID: {user_data['telegram_id']}")
            else:
                # Створюємо нового користувача
                stmt = insert(User).values(**user_data)
                logger.info(f"Створення нового користувача з Telegram ID: {user_data['telegram_id']}")

            await conn.execute(stmt)
        await conn.commit() # Завершуємо транзакцію

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
