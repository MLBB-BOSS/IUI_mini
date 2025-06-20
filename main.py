"""
Головний файл для запуску та ініціалізації Telegram-бота IUI mini.

Цей файл відповідає за:
- Створення та конфігурацію об'єктів Bot та Dispatcher.
- Реєстрацію всіх обробників (хендлерів) з відповідних модулів.
- Налаштування та запуск планувальника завдань (APScheduler).
- Коректний запуск та зупинку процесу поллінгу.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TELEGRAM_BOT_TOKEN, logger, ADMIN_USER_ID
from handlers.general_handlers import register_general_handlers, error_handler
from handlers.vision_handlers import register_vision_handlers
import database
from lobby_manager import check_expired_lobbies

# Отримуємо функцію cmd_go, щоб передати її в vision_handlers
from handlers.general_handlers import cmd_go

async def main() -> None:
    """
    Головна асинхронна функція, що ініціалізує та запускає бота.
    """
    bot_version = "v5.3 (Dependency Fix)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}...")

    # Створюємо об'єкт бота з парсингом HTML за замовчуванням
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # === ВИРІШЕННЯ ПРОБЛЕМИ: TypeError: missing 'bot_info' ===
    # Крок 1: Отримуємо інформацію про нашого бота з API Telegram.
    bot_info = await bot.get_me()
    # Крок 2: Зберігаємо цю інформацію в контексті (в "рюкзаку") диспетчера.
    # Тепер aiogram зможе автоматично передавати об'єкт bot_info в усі фільтри
    # та обробники, які його потребують, вирішуючи проблему з
    # 'missing 1 required positional argument: 'bot_info''.
    dp["bot_info"] = bot_info
    logger.info(f"Інформацію про бота @{bot_info.username} збережено в контексті диспетчера.")

    # Ініціалізація бази даних
    database.initialize_database()

    # Реєстрація обробників з різних модулів
    register_general_handlers(dp)
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go)

    # Реєстрація глобального обробника помилок
    dp.errors.register(error_handler)

    # Налаштування та запуск планувальника для перевірки лобі
    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    scheduler.add_job(check_expired_lobbies, 'interval', minutes=1, args=(bot,))
    scheduler.start()
    logger.info("⏰ Планувальник для перевірки лобі успішно запущено.")

    try:
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID:
            await bot.send_message(str(ADMIN_USER_ID), f"🤖 <b>MLBB IUI mini {bot_version} успішно запущено!</b>")

        # Видаляємо вебхук та починаємо поллінг
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Розпочинаю нескінченний polling...")
        await dp.start_polling(bot)

    finally:
        logger.info("🛑 Зупинка бота та всіх фонових процесів...")
        scheduler.shutdown()
        logger.info("Планувальник завдань зупинено.")
        await bot.session.close()
        logger.info("Сесію бота закрито.")
        logger.info("Роботу бота повністю завершено. До зустрічі!")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот зупинено користувачем (Ctrl+C).")
    except Exception as e:
        logger.critical(f"❌ Непереборна помилка на найвищому рівні: {e}", exc_info=True)
