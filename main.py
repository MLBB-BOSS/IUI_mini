import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TELEGRAM_BOT_TOKEN, logger, ADMIN_USER_ID
# --- ВИРІШЕННЯ ПРОБЛЕМИ: Крок 1 ---
# Імпортуємо не тільки реєстратор, але й саму функцію-обробник
from handlers.general_handlers import register_general_handlers, error_handler, cmd_go
from handlers.vision_handlers import register_vision_handlers
import database
from lobby_manager import check_expired_lobbies

async def main() -> None:
    """
    Головна асинхронна функція, що ініціалізує та запускає бота,
    базу даних та планувальник фонових завдань.
    """
    bot_version = "v3.0.1 (Party Manager - Stable & Hotfixed)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}...")

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    database.initialize_database()

    # Реєстрація обробників
    register_general_handlers(dp)
    
    # --- ВИРІШЕННЯ ПРОБЛЕМИ: Крок 2 ---
    # Передаємо необхідний аргумент `cmd_go_handler_func`
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go)

    dp.errors.register(error_handler)

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    scheduler.add_job(check_expired_lobbies, 'interval', minutes=1, args=(bot,))
    scheduler.start()
    logger.info("⏰ Планувальник для перевірки лобі успішно запущено.")

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            await bot.send_message(str(ADMIN_USER_ID), f"🤖 <b>MLBB IUI mini {bot_version} успішно запущено!</b>")

        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Розпочинаю нескінченний polling...")
        await dp.start_polling(bot)

    finally:
        logger.info("🛑 Зупинка бота та всіх фонових процесів...")
        scheduler.shutdown()
        logger.info("Планувальник завдань зупинено.")
        
        if bot.session:
            await bot.session.close()
            logger.info("Сесію бота закрито.")
        
        logger.info("Роботу бота повністю завершено. До зустрічі!")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот зупинено користувачем (Ctrl+C).")
    except Exception as e:
        logger.critical(f"❌ Непереборна помилка на найвищому рівні при запуску: {e}", exc_info=True)
