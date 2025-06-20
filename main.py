import asyncio
import logging # Логер тепер ініціалізується в config.py
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types # Added types for ErrorEvent
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError 

# Імпорти з проєкту
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID, logger 
# Імпортуємо функції реєстрації та сам глобальний обробник помилок
from handlers.general_handlers import register_general_handlers, error_handler as general_error_handler 
from handlers.vision_handlers import register_vision_handlers
# Імпортуємо cmd_go для передачі в vision_handlers
from handlers.general_handlers import cmd_go


async def main() -> None:
    """Головна функція запуску бота."""
    bot_version = "v2.10.0 (додано аналіз статистики гравця /analyzestats)" 
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    register_general_handlers(dp)
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go) 
    
    # Реєстрація глобального обробника помилок
    @dp.errors()
    async def global_error_handler_wrapper(event: types.ErrorEvent): # Recommended signature
        """
        Global error handler wrapper that catches unhandled exceptions.
        It calls the main error handling logic from general_handlers.
        'bot' instance is taken from the outer scope of main().
        """
        logger.debug(f"Global error wrapper caught exception: {event.exception} in update: {event.update}")
        await general_error_handler(event, bot) # Pass ErrorEvent and bot

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID: # Pythonic check for non-zero/non-None ADMIN_USER_ID
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                
                admin_message_lines = [
                    f"🤖 <b>MLBB IUI mini {bot_version} запущено!</b>",
                    "",
                    f"🆔 @{bot_info.username}",
                    f"⏰ {launch_time_kyiv}",
                    f"🔩 Моделі: Vision: <code>gpt-4o-mini</code>, Текст/Опис: <code>gpt-4.1-turbo</code> (жорстко задані)",
                    "✨ <b>Нові функції:</b>",
                    "  • Додано команду <code>/analyzestats</code> для аналізу скріншотів статистики гравця.",
                    "📂 Структура проєкту та логіка обробки зображень оновлені.",
                    "🟢 Готовий до роботи!"
                ]
                admin_message = "\n".join(admin_message_lines)
                
                await bot.send_message(str(ADMIN_USER_ID), admin_message, parse_mode=ParseMode.HTML) # Ensure ADMIN_USER_ID is str if needed by API
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
