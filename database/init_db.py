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
            logger.info("Checking for 'chat_history' column...")
            add_chat_history_sql = text("ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON")
            await conn.execute(add_chat_history_sql)
            logger.info("Successfully ensured 'chat_history' column exists.")

            # 2. Створення унікального індексу для player_id
            logger.info("Checking for unique index on 'player_id'...")
            # Ідемпотентна команда для PostgreSQL, яка не видасть помилку, якщо індекс вже існує
            add_unique_index_sql = text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id ON users (player_id)")
            await conn.execute(add_unique_index_sql)
            logger.info("Successfully ensured unique index exists for 'player_id'.")

            # --- 🚀 НОВИЙ БЛОК: Додавання колонок для зберігання file_id зображень ---
            logger.info("Checking for profile image file_id columns...")
            
            columns_to_add = [
                "custom_avatar_file_id",
                "profile_screenshot_file_id",
                "stats_screenshot_file_id",
                "heroes_screenshot_file_id"
            ]
            
            for column_name in columns_to_add:
                # Використовуємо VARCHAR без вказання довжини, оскільки file_id може бути довгим
                add_column_sql = text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} VARCHAR")
                await conn.execute(add_column_sql)
                logger.info(f"Successfully ensured '{column_name}' column exists.")
            
            logger.info("All profile image file_id columns are present.")
            # --- Кінець нового блоку ---

            # ✅✅✅ НОВИЙ БЛОК: Додавання колонок для ПОСТІЙНИХ URL зображень ✅✅✅
            logger.info("Checking for profile image permanent URL columns...")
            
            permanent_url_columns = [
                "custom_avatar_permanent_url",
                "profile_screenshot_permanent_url",
                "stats_screenshot_permanent_url",
                "heroes_screenshot_permanent_url"
            ]
            
            for column_name in permanent_url_columns:
                add_url_column_sql = text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} VARCHAR")
                await conn.execute(add_url_column_sql)
                logger.info(f"Successfully ensured '{column_name}' column exists for permanent URLs.")
                
            logger.info("All permanent URL columns for profile images are present.")
            # ✅✅✅ Кінець нового блоку ✅✅✅

        except Exception as e:
            # Логуємо помилку, але не зупиняємо запуск бота.
            logger.error(f"Could not perform a soft migration step: {e}", exc_info=True)
            
    await engine.dispose()
