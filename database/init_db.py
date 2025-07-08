"""
Модуль для ініціалізації бази даних.
Створює всі необхідні таблиці на основі моделей SQLAlchemy
та забезпечує м'які міграції для додаткових колонок.
"""
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from config import ASYNC_DATABASE_URL, logger
from database.models import Base


async def init_db():
    """
    Ініціалізує базу даних: створює таблиці та додає нові колонки й індекси,
    якщо вони ще не існують.
    """
    engine = create_async_engine(ASYNC_DATABASE_URL)
    async with engine.begin() as conn:
        logger.info("Initializing database tables...")
        # Створюємо всі таблиці, визначені в Base.metadata
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully.")

        # --- 🧠 Блок "м'якої" міграції ---
        try:
            # Chat history
            logger.info("Ensuring 'chat_history' column exists...")
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON"
            ))

            # Основні дані профілю
            logger.info("Ensuring basic profile columns exist...")
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS likes_received INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS location TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS squad_name TEXT"
            ))

            # Розширена статистика
            logger.info("Ensuring detailed stats columns exist...")
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS stats_filter_type TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS mvp_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS legendary_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS maniac_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS double_kill_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS most_kills_in_one_game INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS longest_win_streak INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS highest_dmg_per_min INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS highest_gold_per_min INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS savage_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS triple_kill_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS mvp_loss_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS most_assists_in_one_game INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_blood_count INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS highest_dmg_taken_per_min INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS kda_ratio FLOAT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS teamfight_participation_rate FLOAT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_gold_per_min INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_hero_dmg_per_min INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_deaths_per_match FLOAT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_turret_dmg_per_match INTEGER"
            ))

            # Топ-3 улюблених героїв
            logger.info("Ensuring favorite heroes columns exist...")
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero1_name TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero1_matches INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero1_win_rate FLOAT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero2_name TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero2_matches INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero2_win_rate FLOAT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero3_name TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero3_matches INTEGER"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS hero3_win_rate FLOAT"
            ))

            # Колонки для зображень
            logger.info("Ensuring image file_id and URL columns exist...")
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
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_file_id TEXT"
            ))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_permanent_url TEXT"
            ))

            # Унікальний індекс на player_id
            logger.info("Ensuring unique index on 'player_id' exists...")
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id ON users (player_id)"
            ))

            logger.info("Soft migration completed successfully.")
        except Exception as e:
            logger.error(f"Soft migration step failed: {e}", exc_info=True)

    await engine.dispose()
