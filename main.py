import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# Імпорти з проєкту
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID, logger
from handlers.general_handlers import (
    register_general_handlers, 
    set_bot_commands,
    error_handler as general_error_handler
)
from handlers.vision_handlers import register_vision_handlers
from handlers.registration_handler import register_registration_handlers
# Ми можемо видалити цей імпорт, оскільки він більше не потрібен тут
# from handlers.general_handlers import cmd_go


async def main() -> None:
    """Головна функція запуску бота."""
    bot_version = "v3.0.2 (Router-Fix)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Встановлюємо команди бота при старті
    await set_bot_commands(bot)

    #  критично важлива зміна: реєструємо специфічні роутери ПЕРЕД загальними
    register_registration_handlers(dp)
    
    # Тепер реєструємо решту роутерів
    # Ми передаємо `dp` замість `cmd_go`, оскільки `vision_handlers` тепер буде сам реєструвати свої команди
    register_vision_handlers(dp) 
    register_general_handlers(dp)

    # Реєстрація глобального обробника помилок
    @dp.errors()
    async def global_error_handler_wrapper(event: types.ErrorEvent):
        """
        Global error handler wrapper that catches unhandled exceptions.
        It calls the main error handling logic from general_handlers.
        'bot' instance is taken from the outer scope of main().
        """
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
                    "  • Виправлено порядок реєстрації роутерів для коректної роботи команд.",
                    "🟢 Готовий до роботи!"
                ]
                admin_message = "\n".join(admin_message_lines)
                
                await bot.send_message(str(ADMIN_USER_ID), admin_message, parse_mode=ParseMode.HTML)
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}", exc_info=True)

        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt).")
    except TelegramAPIError as e:
        logger.critical(f"Критична помилка Telegram API під час запуску або роботи: {e}", exc_info=True)
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
