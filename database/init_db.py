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
    Ініціалізує базу даних, створюючи таблиці та перевіряючи/додаючи нові колонки.
    """
    engine = create_async_engine(ASYNC_DATABASE_URL)
    async with engine.begin() as conn:
        logger.info("Initializing database tables...")
        # Створюємо всі таблиці, визначені в Base.metadata (якщо вони не існують)
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully (if they did not exist).")

        # --- 🧠 Блок "м'якої" міграції для додавання відсутніх колонок ---
        try:
            logger.info("Checking for missing 'chat_history' column in 'users' table...")
            # SQL-запит для додавання колонки, тільки якщо вона не існує.
            # Це ідемпотентна операція, безпечна для повторного запуску.
            add_column_sql = text("ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON")
            await conn.execute(add_column_sql)
            logger.info("Successfully ensured 'chat_history' column exists in 'users' table.")
        except Exception as e:
            # Логуємо помилку, але не зупиняємо запуск бота.
            # Можливо, таблиці ще не існувало, і вона створиться вище.
            logger.error(f"Could not perform soft migration for 'chat_history' column: {e}", exc_info=True)
            
    await engine.dispose()
