import asyncio
import logging # Логер тепер ініціалізується в config.py
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError # Може знадобитися для main

# Імпорти з проєкту
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID, logger # Використовуємо logger з config
# Імпортуємо функції реєстрації та сам глобальний обробник помилок
from handlers.general_handlers import register_general_handlers, error_handler as general_error_handler # Перейменовуємо, щоб уникнути конфлікту імен
from handlers.vision_handlers import register_vision_handlers
# Імпортуємо cmd_go для передачі в vision_handlers
from handlers.general_handlers import cmd_go


# Головний логер програми тепер налаштовано в config.py
# logger = logging.getLogger(__name__) # Цей рядок більше не потрібен тут

async def main() -> None:
    """Головна функція запуску бота."""
    bot_version = "v2.9.1 (рефакторинг, покращена обробка HTML та помилок)" # Можна винести в config
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    # Ініціалізація бота з токеном з конфігурації
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Реєстрація обробників
    register_general_handlers(dp)
    # Передаємо функцію cmd_go в register_vision_handlers
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go) 
    
    # Реєстрація глобального обробника помилок
    # Передаємо bot як аргумент в обробник помилок, якщо він там потрібен
    # dp.errors.register(general_error_handler) # Тепер error_handler приймає bot
    # Потрібно використовувати lambda або functools.partial, якщо обробник помилок приймає додаткові аргументи
    # dp.errors.register(lambda update, exception: general_error_handler(update, exception, bot))
    # Або краще, якщо error_handler завжди приймає bot:
    @dp.errors()
    async def global_error_handler_wrapper(update_event, exception: Exception):
        # Тепер bot доступний в цьому скоупі
        await general_error_handler(update_event, exception, bot)


    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        if ADMIN_USER_ID != 0: # Використовуємо ADMIN_USER_ID з конфігурації
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                admin_message = (
                    f"🤖 <b>MLBB IUI mini {bot_version} запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🔩 Моделі: Vision: <code>gpt-4o-mini</code>, Текст/Опис: <code>gpt-4.1</code> (жорстко задані)\n"
                    f"📂 Структура проєкту оновлена (рефакторинг).\n"
                    f"🟢 Готовий до роботи!"
                )
                await bot.send_message(ADMIN_USER_ID, admin_message, parse_mode=ParseMode.HTML)
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}")

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
        if bot.session and hasattr(bot.session, "close") and not bot.session.closed:
            try:
                await bot.session.close()
                logger.info("Сесію HTTP клієнта Bot закрито.")
            except Exception as e:
                logger.error(f"Помилка під час закриття сесії HTTP клієнта Bot: {e}", exc_info=True)
        
        # Тут можна було б закривати сесію MLBBChatGPT, якби вона була глобальною,
        # але вона створюється і закривається в контекстному менеджері.

        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    # Налаштування логування відбувається при імпорті config.py
    asyncio.run(main())
