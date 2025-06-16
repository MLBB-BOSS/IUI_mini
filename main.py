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
from handlers.general_handlers import register_general_handlers, error_handler as general_error_handler
from handlers.vision_handlers import register_vision_handlers
# Імпортуємо cmd_go для передачі в vision_handlers
from handlers.general_handlers import cmd_go


async def main() -> None:
    """Головна функція запуску бота."""
    # Оновлюємо версію, щоб відобразити нову функціональність
    bot_version = "v2.10.0 (додано аналіз статистики гравця /analyzestats)" 
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    # Ініціалізація бота з токеном з конфігурації
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Реєстрація обробників
    register_general_handlers(dp)
    # Передаємо функцію cmd_go в register_vision_handlers.
    # register_vision_handlers тепер включає реєстрацію /analyzestats.
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go) 
    
    # Реєстрація глобального обробника помилок
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
                
                # Оновлюємо повідомлення для адміна
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
        # Закриття сесії HTTP клієнта бота (якщо вона була створена і відкрита)
        # У aiogram 3.x сесія зазвичай керується самим Bot об'єктом і закривається при його видаленні
        # або при завершенні роботи dp.start_polling.
        # Явний виклик close() для bot.session може бути корисним для певності.
        if bot and hasattr(bot, 'session') and bot.session and not bot.session.closed:
            try:
                await bot.session.close()
                logger.info("Сесію HTTP клієнта Bot закрито.")
            except Exception as e:
                logger.error(f"Помилка під час закриття сесії HTTP клієнта Bot: {e}", exc_info=True)
        
        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    # Налаштування логування відбувається при імпорті config.py
    # (або тут, якщо config.py не імпортується першим або не налаштовує логування глобально)
    asyncio.run(main())
