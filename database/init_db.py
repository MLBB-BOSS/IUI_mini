"""
Модуль для ініціалізації бази даних.
Створює всі необхідні таблиці на основі моделей SQLAlchemy
та забезпечує м'які міграції для додаткових колонок.
"""
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from config import ASYNC_DATABASE_URL, logger
from database.models import Base


async def init_db() -> None:
    """
    Ініціалізує базу даних: створює таблиці та додає нові колонки й індекси,
    якщо вони ще не існують, використовуючи паралельні запити.
    """
    engine = create_async_engine(ASYNC_DATABASE_URL)
    async with engine.begin() as conn:
        logger.info("Initializing database tables (including user_settings)...")
        # Base.metadata.create_all автоматично знайде всі успадковані класи,
        # включаючи User та нову UserSettings.
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully.")

        try:
            logger.info("Applying soft migrations for 'users' table...")
            
            # --- 🚀 MIGRATION: Parallel execution with TaskGroup ---
            async with asyncio.TaskGroup() as tg:
                # Список усіх ALTER TABLE запитів
                alter_queries = [
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS likes_received INTEGER",
                    # ... (решта міграцій для 'users' залишаються без змін) ...
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS location TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS squad_name TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_filter_type TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mvp_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS legendary_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS maniac_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS double_kill_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS most_kills_in_one_game INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS longest_win_streak INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS highest_dmg_per_min INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS highest_gold_per_min INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS savage_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS triple_kill_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS mvp_loss_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS most_assists_in_one_game INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_blood_count INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS highest_dmg_taken_per_min INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS kda_ratio FLOAT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS teamfight_participation_rate FLOAT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_gold_per_min INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_hero_dmg_per_min INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_deaths_per_match FLOAT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_turret_dmg_per_match INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero1_name TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero1_matches INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero1_win_rate FLOAT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero2_name TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero2_matches INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero2_win_rate FLOAT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero3_name TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero3_matches INTEGER",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero3_win_rate FLOAT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS basic_profile_file_id TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS basic_profile_permanent_url TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_photo_file_id TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_photo_permanent_url TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS heroes_photo_file_id TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS heroes_photo_permanent_url TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_file_id TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_permanent_url TEXT",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_muted BOOLEAN DEFAULT false",
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id ON users (player_id)",
                ]
                
                # Створюємо завдання для кожного запиту
                for query in alter_queries:
                    tg.create_task(conn.execute(text(query)))
            
            logger.info("Soft migrations completed successfully.")
        except* Exception as eg:
            for e in eg.exceptions:
                logger.error(f"Soft migration failed: {e}", exc_info=e)

    await engine.dispose()
