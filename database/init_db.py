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
            logger.info("Applying soft migrations for 'users' table...")

            # Chat history
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history JSON"
            ))

            # Основні дані профілю
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
            stats_cols = [
                "stats_filter_type TEXT",
                "mvp_count INTEGER",
                "legendary_count INTEGER",
                "maniac_count INTEGER",
                "double_kill_count INTEGER",
                "most_kills_in_one_game INTEGER",
                "longest_win_streak INTEGER",
                "highest_dmg_per_min INTEGER",
                "highest_gold_per_min INTEGER",
                "savage_count INTEGER",
                "triple_kill_count INTEGER",
                "mvp_loss_count INTEGER",
                "most_assists_in_one_game INTEGER",
                "first_blood_count INTEGER",
                "highest_dmg_taken_per_min INTEGER",
                "kda_ratio FLOAT",
                "teamfight_participation_rate FLOAT",
                "avg_gold_per_min INTEGER",
                "avg_hero_dmg_per_min INTEGER",
                "avg_deaths_per_match FLOAT",
                "avg_turret_dmg_per_match INTEGER",
            ]
            for col in stats_cols:
                await conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col}"
                ))

            # Топ-3 улюблених героїв
            hero_cols = [
                ("hero1_name", "TEXT"), ("hero1_matches", "INTEGER"), ("hero1_win_rate", "FLOAT"),
                ("hero2_name", "TEXT"), ("hero2_matches", "INTEGER"), ("hero2_win_rate", "FLOAT"),
                ("hero3_name", "TEXT"), ("hero3_matches", "INTEGER"), ("hero3_win_rate", "FLOAT"),
            ]
            for name, typ in hero_cols:
                await conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {typ}"
                ))

            # Колонки для зображень
            image_cols = [
                ("basic_profile_file_id", "TEXT"),
                ("basic_profile_permanent_url", "TEXT"),
                ("stats_photo_file_id", "TEXT"),
                ("stats_photo_permanent_url", "TEXT"),
                ("heroes_photo_file_id", "TEXT"),
                ("heroes_photo_permanent_url", "TEXT"),
                ("avatar_file_id", "TEXT"),
                ("avatar_permanent_url", "TEXT"),
            ]
            for name, typ in image_cols:
                await conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {typ}"
                ))

            # Унікальний індекс на player_id
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id "
                "ON users (player_id)"
            ))

            logger.info("Soft migrations completed successfully.")
        except Exception as e:
            logger.error(f"Soft migration failed: {e}", exc_info=True)

    await engine.dispose()