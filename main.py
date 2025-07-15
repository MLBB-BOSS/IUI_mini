import asyncio
import logging
import os
import greenlet  # ❗️ Гарантуємо, що greenlet завантажено
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# Імпорти з проєкту
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID, logger, ASYNC_DATABASE_URL
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from database.init_db import init_db
from handlers.general_handlers import (
    register_general_handlers, 
    set_bot_commands,
    error_handler as general_error_handler,
    cmd_go
)
from handlers.vision_handlers import register_vision_handlers
from handlers.registration_handler import register_registration_handlers
# 👇 ВАЖЛИВО: Імпортуємо реєстратор для нової гри
from games.reaction.handlers import register_reaction_handlers


async def sanitize_database():
    """
    Одноразова функція для очищення бази даних від дублікатів player_id.
    (Код функції залишається без змін)
    """
    logger.info("🩺 Starting database sanitization process...")
    engine = create_async_engine(ASYNC_DATABASE_URL)
    async with engine.connect() as conn:
        try:
            async with conn.begin():
                find_duplicates_sql = text("""
                    SELECT player_id, COUNT(*)
                    FROM users
                    GROUP BY player_id
                    HAVING COUNT(*) > 1
                """)
                duplicates_result = await conn.execute(find_duplicates_sql)
                duplicate_player_ids = [row[0] for row in duplicates_result.all()]

                if not duplicate_player_ids:
                    logger.info("✅ No duplicate player_id found. Database is clean.")
                else:
                    logger.warning(f"Found duplicate player_ids: {duplicate_player_ids}. Proceeding with cleanup...")
                    cleanup_sql = text("""
                        DELETE FROM users
                        WHERE ctid IN (
                            SELECT ctid
                            FROM (
                                SELECT 
                                    ctid,
                                    ROW_NUMBER() OVER(PARTITION BY player_id ORDER BY created_at DESC) as rn
                                FROM users
                                WHERE player_id = ANY(:player_ids)
                            ) as sub
                            WHERE rn > 1
                        )
                    """)
                    result = await conn.execute(cleanup_sql, {"player_ids": duplicate_player_ids})
                    logger.info(f"✅ Successfully deleted {result.rowcount} duplicate user entries.")

            async with conn.begin():
                logger.info("Attempting to create unique index on 'player_id' after sanitization...")
                add_unique_index_sql = text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_player_id ON users (player_id)")
                await conn.execute(add_unique_index_sql)
                logger.info("✅ Successfully ensured unique index exists for 'player_id'.")

        except Exception as e:
            logger.error(f"❌ Critical error during database sanitization: {e}", exc_info=True)
        finally:
            await conn.close()

    await engine.dispose()
    logger.info("🩺 Database sanitization process finished.")


async def main() -> None:
    """Головна функція запуску бота."""
    bot_version = "v4.1.0 (Reaction Game Fix)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    await sanitize_database()
    await init_db()

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    await set_bot_commands(bot)

    # --- РЕЄСТРАЦІЯ ВСІХ РОУТЕРІВ ---
    register_registration_handlers(dp)
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go) 
    register_general_handlers(dp)
    register_reaction_handlers(dp)  # 👈 ВАЖЛИВО: Реєструємо роутер гри

    # Реєстрація глобального обробника помилок
    @dp.errors()
    async def global_error_handler_wrapper(event: types.ErrorEvent):
        logger.debug(f"Global error wrapper caught exception: {event.exception} in update: {event.update}")
        await general_error_handler(event, bot)

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                
                admin_message_lines = [
                    f"🤖 <b>MLBB IUI mini {bot_version} запущено!</b>",
                    "",
                    f"🆔 @{bot_info.username}",
                    f"⏰ {launch_time_kyiv}",
                    "✨ <b>Зміни:</b>",
                    "  • Зареєстровано модуль гри 'Reaction Time'.",
                    "  • Виправлено логіку розпізнавання команд гри.",
                    "🟢 Готовий до роботи!"
                ]
                admin_message = "\n".join(admin_message_lines)
                
                await bot.send_message(str(ADMIN_USER_ID), admin_message, parse_mode=ParseMode.HTML)
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}", exc_info=True)

        logger.info("Розпочинаю polling...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"Непередбачена критична помилка під час запуску або роботи: {e}", exc_info=True)
    finally:
        logger.info("🛑 Зупинка бота та закриття сесій...")
        if bot and hasattr(bot, 'session') and bot.session and not bot.session.closed:
            try:
                await bot.session.close()
                logger.info("Сесію HTTP клієнта Bot закрито.")
            except Exception as e:
                logger.error(f"Помилка під час закриття сесії HTTP клієнта Bot: {e}", exc_info=True)
        
        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    asyncio.run(main())
