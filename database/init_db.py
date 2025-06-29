"""
Модуль для ініціалізації бази даних.
Створює всі необхідні таблиці на основі моделей SQLAlchemy.
"""
from sqlalchemy.ext.asyncio import create_async_engine
from config import ASYNC_DATABASE_URL, logger
from database.models import Base

async def init_db():
    """
    Ініціалізує базу даних, створюючи таблиці, якщо вони не існують.
    """
    engine = create_async_engine(ASYNC_DATABASE_URL)
    async with engine.begin() as conn:
        logger.info("Initializing database tables...")
        # Створюємо всі таблиці, визначені в Base.metadata
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully (if they did not exist).")
    await engine.dispose()
