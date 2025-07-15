"""
Функції для взаємодії з базою даних (CRUD) для гри на реакцію.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import logger
# Використовуємо спільний engine з основного модуля БД
from database.crud import engine


async def save_reaction_score(user_id: int, time_ms: int) -> None:
    """
    Зберігає або оновлює найкращий час реакції для користувача.
    
    Використовує 'INSERT ... ON CONFLICT' для атомарного оновлення,
    що є більш ефективним, ніж окремі операції SELECT та UPDATE.
    
    Args:
        user_id: Telegram ID користувача.
        time_ms: Час реакції в мілісекундах.
    """
    async with engine.connect() as conn:
        async with conn.begin():
            try:
                # Цей запит або вставить новий запис, або оновить існуючий,
                # якщо новий час реакції кращий за старий.
                stmt = text("""
                    INSERT INTO reaction_scores (user_id, best_time, last_played_at)
                    VALUES (:user_id, :time_ms, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        best_time = LEAST(reaction_scores.best_time, :time_ms),
                        last_played_at = NOW();
                """)
                await conn.execute(stmt, {"user_id": user_id, "time_ms": time_ms})
                logger.info(f"Saved reaction score for user {user_id}: {time_ms}ms")
            except SQLAlchemyError as e:
                logger.error(
                    f"A database error occurred while saving reaction score "
                    f"for user {user_id}: {e}",
                    exc_info=True
                )
                # Ролбек транзакції відбудеться автоматично при виході з блоку `async with conn.begin()`


async def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    """
    Отримує таблицю лідерів з найкращими результатами.
    
    Args:
        limit: Кількість позицій у таблиці лідерів.

    Returns:
        Список словників з даними про найкращих гравців.
        Приклад: [{'nickname': 'Player1', 'best_time': 150, 'telegram_id': 123}, ...]
    """
    # ❗️ ВИПРАВЛЕННЯ: Додано users.telegram_id до SELECT
    # Запит спрощено, оскільки тепер ми не потребуємо агрегації MIN/GROUP BY
    query = text("""
        SELECT 
            u.nickname, 
            rs.best_time,
            u.telegram_id
        FROM reaction_scores rs
        JOIN users u ON rs.user_id = u.telegram_id
        ORDER BY rs.best_time ASC
        LIMIT :limit;
    """)
    
    async with engine.connect() as conn:
        try:
            result = await conn.execute(query, {"limit": limit})
            # Перетворюємо результат на список словників для зручності
            leaderboard_data = [dict(row._mapping) for row in result.all()]
            logger.info(f"Successfully fetched leaderboard with {len(leaderboard_data)} records.")
            return leaderboard_data
        except SQLAlchemyError as e:
            logger.error(f"Failed to fetch leaderboard from DB: {e}", exc_info=True)
            # У випадку помилки повертаємо порожній список, щоб не зламати логіку бота
            return []
