import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError

from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID

# Імпортуємо роутери та обробники з відповідних модулів
# Це робить структуру чистою та підтримуваною
from app.handlers.general_handlers import general_router, cmd_go, general_error_handler
from app.handlers.vision_handlers import register_vision_handlers # Припускаючи, що цей файл існує
from app.handlers.gemini_handlers import gemini_router # Припускаючи, що цей файл існує

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    """
    Головна асинхронна функція. Ініціалізує бота, диспетчер,
    реєструє обробники повідомлень та помилок, і запускає polling.
    """
    bot_version = "v3.2.0 (стабільність та обробка помилок)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    storage = MemoryStorage()
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)

    # Реєстрація роутерів з різних модулів
    dp.include_router(general_router)
    # Приклад реєстрації інших обробників
    # register_vision_handlers(dp, cmd_go_handler_func=cmd_go)
    # dp.include_router(gemini_router)

    # Реєстрація глобального обробника помилок.
    # Передаємо екземпляр бота в обробник для можливості надсилати повідомлення.
    dp.errors.register(general_error_handler, bot=bot)

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")

        if ADMIN_USER_ID:
            await notify_admin_on_startup(bot, bot_info, bot_version)

        logger.info("Розпочинаю polling...")
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

async def notify_admin_on_startup(bot: Bot, bot_info: types.User, bot_version: str):
    """
    Надсилає детальне інформаційне повідомлення адміністратору під час запуску бота.
    """
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
            "  • Виправлено критичну помилку `AttributeError`.",
            "  • Оновлено обробник помилок до стандарту `aiogram 3.x`.",
            "  • Впроваджено сповіщення адміністратора про помилки.",
            "🟢 Готовий до роботи!"
        ]
        admin_message = "\n".join(admin_message_lines)

        await bot.send_message(str(ADMIN_USER_ID), admin_message, parse_mode=ParseMode.HTML)
        logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
    except Exception as e:
        logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
