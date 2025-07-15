"""
Функції для взаємодії з базою даних (CRUD) для гри на реакцію.
"""
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from config import logger
from database.crud import engine  # Використовуємо спільний engine
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
            # Ця помилка може виникнути, якщо user_telegram_id не існує в таблиці 'users'
            # через обмеження зовнішнього ключа (ForeignKey).
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

    Args:
        limit: Кількість позицій у таблиці лідерів.

    Returns:
        Список словників з даними про найкращих гравців.
    """
    # TODO: Реалізувати SQL-запит для отримання топ-N гравців,
    # використовуючи SELECT, JOIN з таблицею users (для нікнеймів),
    # ORDER BY та LIMIT.
    logger.info("Leaderboard function is not yet implemented.")
    return []
