import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# Імпорт власних модулів
from config_reader import config
# Правильний імпорт роутера та обробника помилок згідно з новою структурою
from app.handlers.general_handlers import general_router, general_error_handler
# Наступні модулі ще не створені, тому їх імпорт закоментовано, щоб уникнути ModuleNotFoundError.
# Ви зможете їх розкоментувати, коли створите відповідні файли.
# from app.handlers.vision_handlers import register_vision_handlers
# from app.handlers.gemini_handlers import gemini_router

# Налаштування змінних оточення та логування
TELEGRAM_BOT_TOKEN = config.bot_token.get_secret_value()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def notify_admin_on_startup(bot: Bot, bot_info: types.User, bot_version: str):
    """
    Надсилає детальне інформаційне повідомлення адміністратору під час запуску бота.
    """
    if not ADMIN_USER_ID:
        return
    try:
        kyiv_tz = timezone(timedelta(hours=3))
        launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')

        admin_message_lines = [
            f"🤖 <b>MLBB IUI mini {bot_version} запущено!</b>",
            "",
            f"🆔 @{bot_info.username}",
            f"⏰ {launch_time_kyiv}",
            "---",
            "✨ <b>Ключове оновлення:</b>",
            "  • ✅ Виправлено критичну помилку `AttributeError`.",
            "  • ✅ Оновлено обробник помилок до стандарту `aiogram 3.x`.",
            "  • ✅ Впроваджено надійні сповіщення адміністратора про помилки.",
            "🟢 Готовий до роботи!"
        ]
        await bot.send_message(
            str(ADMIN_USER_ID),
            "\n".join(admin_message_lines),
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
    except Exception as e:
        logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}", exc_info=True)

async def main():
    """
    Головна асинхронна функція. Ініціалізує бота, диспетчер,
    реєструє роутери та обробник помилок, і запускає polling.
    """
    bot_version = "v3.2.0 (стабільність та обробка помилок)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    storage = MemoryStorage()
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)

    # Реєстрація роутерів з різних модулів
    dp.include_router(general_router)
    # Коли ви створите інші обробники, ви зможете їх підключити тут:
    # dp.include_router(vision_router)
    # dp.include_router(gemini_router)

    # Реєстрація глобального обробника помилок.
    # Передаємо екземпляр бота в обробник для можливості надсилати повідомлення.
    dp.errors.register(general_error_handler, bot=bot)

    try:
        # Отримуємо інформацію про бота перед запуском
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")

        # Сповіщаємо адміністратора про успішний запуск
        await notify_admin_on_startup(bot, bot_info, bot_version)

        logger.info("Розпочинаю polling...")
        # Видаляємо вебхук та накопичені оновлення, щоб уникнути обробки старих повідомлень
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt).")
    except TelegramAPIError as e:
        logger.critical(f"Критична помилка Telegram API під час запуску: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"Непередбачена критична помилка під час запуску: {e}", exc_info=True)
    finally:
        logger.info("🛑 Зупинка бота та закриття сесій...")
        await dp.storage.close()
        await bot.session.close()
        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    asyncio.run(main())
