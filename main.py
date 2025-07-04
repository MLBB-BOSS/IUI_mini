"""
Головний файл для запуску Telegram-бота.

Відповідає за:
- Ініціалізацію конфігурації та логування.
- Створення та налаштування об'єктів бота та диспетчера.
- Реєстрацію обробників (хендлерів).
- Встановлення кастомних мідлварі (проміжних обробників).
- Запуск та коректну зупинку бота.
"""
import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Імпорти з нашого проєкту
from config import BOT_TOKEN, ASYNC_DATABASE_URL, logger
from handlers.general_handlers import register_general_handlers, error_handler, set_bot_commands
from handlers.profile_handlers import register_profile_handlers
from handlers.vision_handlers import register_vision_handlers
from middlewares.db_middleware import DbSessionMiddleware

async def main():
    """
    Основна асинхронна функція для запуску бота.
    """
    # Створення асинхронного рушія та фабрики сесій для SQLAlchemy
    try:
        async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)
        session_maker = async_sessionmaker(async_engine, expire_on_commit=False)
        logger.info("✅ Асинхронний рушій бази даних успішно створено.")
    except Exception as e:
        logger.critical(f"❌ Критична помилка при створенні рушія БД: {e}", exc_info=True)
        return

    # Ініціалізація бота та диспетчера
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()

    # Реєстрація мідлварі для передачі сесії БД в обробники
    dp.update.middleware(DbSessionMiddleware(session_pool=session_maker))
    logger.info("✅ Мідлварь для сесій бази даних успішно зареєстровано.")

    # Реєстрація обробників
    register_general_handlers(dp)
    register_profile_handlers(dp)
    register_vision_handlers(dp)

    # Реєстрація глобального обробника помилок
    dp.errors.register(error_handler)
    logger.info("✅ Глобальний обробник помилок успішно зареєстровано.")

    # Встановлення команд бота при старті
    await set_bot_commands(bot)

    # Запуск бота
    logger.info("🚀 Запуск MLBB IUI mini v3.2.0 (Profile-Refactor)...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("🛑 Зупинка бота та закриття сесій...")
        # Коректне закриття сесії бота
        if bot and hasattr(bot, 'session') and bot.session and not bot.session.is_closed(): # CORRECTED LINE
            await bot.session.close()
            logger.info("Сесію бота успішно закрито.")
        # Закриття пулу з'єднань з БД
        await async_engine.dispose()
        logger.info("Пул з'єднань з базою даних успішно закрито.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.warning("Бот був зупинений вручну (KeyboardInterrupt/SystemExit).")
    except Exception as e:
        logger.critical(f"❌ Неперехоплена помилка на верхньому рівні: {e}", exc_info=True)
