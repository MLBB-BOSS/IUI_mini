"""
Модуль для ініціалізації бази даних.
Створює всі необхідні таблиці на основі моделей SQLAlchemy.
"""
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from config import ASYNC_DATABASE_URL, logger
from database.models import Base

async def init_db():
    """
    Ініціалізує базу даних, створюючи таблиці та перевіряючи/додаючи нові колонки та індекси.
    """
    engine = create_async_engine(ASYNC_DATABASE_URL)
    async with engine.begin() as conn:
        logger.info("Initializing database tables...")
        # Створюємо всі таблиці, визначені в Base.metadata (якщо вони не існують)
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully (if they did not exist).")

        # --- 🧠 Блок "м'якої" міграції ---
        try:
            # 1. Додавання колонки chat_history
            logger.info("Checking for missing 'chat_history' column...")
            add_column_sql = text("ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON")
            await conn.execute(add_column_sql)
            logger.info("Successfully ensured 'chat_history' column exists.")

            # 2. Створення унікального індексу для player_id
            logger.info("Checking for unique index on 'player_id'...")
            # Ідемпотентна команда для PostgreSQL, яка не видасть помилку, якщо індекс вже існує
            add_unique_index_sql = text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id ON users (player_id)")
            await conn.execute(add_unique_index_sql)
            logger.info("Successfully ensured unique index exists for 'player_id'.")

        except Exception as e:
            # Логуємо помилку, але не зупиняємо запуск бота.
            logger.error(f"Could not perform a soft migration step: {e}", exc_info=True)
            
    await engine.dispose()
