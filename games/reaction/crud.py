"""
Функції для взаємодії з базою даних (CRUD) для гри на реакцію.
"""
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from config import logger
from database.crud import engine  # Використовуємо спільний engine
from database.models import User
from games.reaction.models import ReactionGameScore


async def save_reaction_score(user_telegram_id: int, reaction_time_ms: int) -> bool:
    """
    Зберігає результат гри на реакцію в базу даних.

    Args:
        user_telegram_id: Telegram ID користувача.
        reaction_time_ms: Час реакції в мілісекундах.

    Returns:
        True, якщо результат успішно збережено, інакше False.
    """
    stmt = insert(ReactionGameScore).values(
        user_telegram_id=user_telegram_id,
        reaction_time_ms=reaction_time_ms
    )

    async with engine.connect() as conn:
        try:
            await conn.execute(stmt)
            await conn.commit()
            logger.info(
                f"Saved reaction score for user {user_telegram_id}: {reaction_time_ms}ms"
            )
            return True
        except IntegrityError as e:
            await conn.rollback()
            logger.warning(
                f"Could not save reaction score for user {user_telegram_id} due to "
                f"IntegrityError (user might not exist): {e}"
            )
            return False
        except SQLAlchemyError as e:
            await conn.rollback()
            logger.error(
                f"A database error occurred while saving reaction score for user "
                f"{user_telegram_id}: {e}",
                exc_info=True
            )
            return False


async def get_leaderboard(limit: int = 10) -> list[dict]:
    """
    Отримує таблицю лідерів з найкращими результатами.

    Вибирає найкращий час для кожного унікального гравця,
    об'єднує з таблицею користувачів для отримання нікнейму
    та сортує за зростанням часу реакції.

    Args:
        limit: Кількість позицій у таблиці лідерів.

    Returns:
        Список словників з даними про найкращих гравців.
        Приклад: [{'nickname': 'Player1', 'best_time': 150}, ...]
    """
    # Використовуємо сирий SQL запит для більшої гнучкості з MIN та GROUP BY,
    # що є більш читабельним для такої задачі, ніж SQLAlchemy ORM/Core.
    # Параметризація (:limit) забезпечує захист від ін'єкцій.
    query = text("""
        SELECT
            u.nickname,
            MIN(rs.reaction_time_ms) as best_time
        FROM reaction_game_scores rs
        JOIN users u ON u.telegram_id = rs.user_telegram_id
        GROUP BY u.nickname
        ORDER BY best_time ASC
        LIMIT :limit;
    """)
    
    leaderboard_data = []
    async with engine.connect() as conn:
        try:
            result = await conn.execute(query, {"limit": limit})
            leaderboard_data = [
                {"nickname": row[0], "best_time": row[1]} for row in result.fetchall()
            ]
            logger.info(f"Successfully fetched leaderboard with {len(leaderboard_data)} records.")
        except SQLAlchemyError as e:
            logger.error(f"Failed to fetch leaderboard from DB: {e}", exc_info=True)
            # У випадку помилки повертаємо порожній список, щоб не зламати бота
            return []
            
    return leaderboard_data
