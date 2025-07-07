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
            # 1. Додавання chat_history
            logger.info("Ensuring 'chat_history' column exists...")
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON"
            ))

            # 2. Нові колонки для фото профілю
            logger.info("Ensuring profile image columns exist...")
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS basic_profile_file_id TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS basic_profile_permanent_url TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_photo_file_id TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_photo_permanent_url TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS heroes_photo_file_id TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS heroes_photo_permanent_url TEXT"
            ))

            # 3. Унікальний індекс для player_id
            logger.info("Ensuring unique index on 'player_id' exists...")
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id ON users (player_id)"
            ))

            logger.info("Soft migration completed successfully.")
        except Exception as e:
            # Логуємо помилку, але не зупиняємо запуск бота.
            logger.error(f"Soft migration step failed: {e}", exc_info=True)

    await engine.dispose()
