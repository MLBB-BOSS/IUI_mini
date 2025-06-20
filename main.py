import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TELEGRAM_BOT_TOKEN, logger, ADMIN_USER_ID
from handlers.general_handlers import register_general_handlers, error_handler
from handlers.vision_handlers import register_vision_handlers
import database
from lobby_manager import check_expired_lobbies

async def main() -> None:
    """Головна функція, що запускає бота та фонові задачі."""
    bot_version = "v3.0.0 (Party Manager 3.0)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}...")

    # Ініціалізація бота та диспетчера
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Ініціалізація бази даних перед реєстрацією обробників
    database.initialize_database()

    # Реєстрація обробників
    register_general_handlers(dp)
    register_vision_handlers(dp)

    # Реєстрація глобального обробника помилок
    dp.errors.register(error_handler)

    # Налаштування та запуск планувальника для перевірки лобі
    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    scheduler.add_job(check_expired_lobbies, 'interval', minutes=1, args=(bot,))
    scheduler.start()
    logger.info("⏰ Планувальник для перевірки лобі запущено.")

    try:
        # Інформаційне повідомлення адміну про запуск
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            await bot.send_message(str(ADMIN_USER_ID), f"🤖 <b>MLBB IUI mini {bot_version} успішно запущено!</b>")

        # Пропускаємо старі оновлення та запускаємо polling
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)

    finally:
        scheduler.shutdown()
        logger.info("Планувальник зупинено.")
        await bot.session.close()
        logger.info("Сесію бота закрито. Роботу завершено.")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот зупинено користувачем.")
    except Exception as e:
        logger.critical(f"❌ Непереборна помилка при запуску бота: {e}", exc_info=True)
