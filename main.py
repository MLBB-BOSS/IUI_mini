"""
Головний файл запуску бота (entrypoint).

Відповідає за ініціалізацію, конфігурацію та запуск бота,
а також за реєстрацію всіх обробників (роутерів) та граційну зупинку.
Архітектура відповідає стандартам aiogram 3.x.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# Імпорти з нашого проєкту
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID, logger
# Імпортуємо головну функцію реєстрації та сам обробник помилок
from handlers.general_handlers import register_general_handlers, error_handler
# Імпортуємо функцію реєстрації для обробників зображень
from handlers.vision_handlers import register_vision_handlers

async def main() -> None:
    """
    Головна асинхронна функція для запуску бота.

    Виконує наступні кроки:
    1. Ініціалізує об'єкти Bot та Dispatcher.
    2. Реєструє глобальний обробник помилок за сучасним стандартом.
    3. Реєструє всі роутери (general, vision, etc.).
    4. Надсилає повідомлення адміністратору про успішний запуск.
    5. Запускає long-polling для отримання оновлень від Telegram.
    6. Забезпечує коректне закриття сесій при зупинці.
    """
    bot_version = "v3.0.0 (Архітектура FSM та Decoupling)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # КРОК 1: РЕЄСТРАЦІЯ ГЛОБАЛЬНОГО ОБРОБНИКА ПОМИЛОК
    # Це рекомендований, чистий та декларативний спосіб для aiogram 3.x.
    # Ми реєструємо `error_handler` напряму, без зайвих функцій-обгорток.
    dp.errors.register(error_handler, F.update)
    logger.info("Глобальний обробник помилок успішно зареєстровано.")

    # КРОК 2: РЕЄСТРАЦІЯ ВСІХ РОУТЕРІВ
    # Кожна функція реєстрації відповідає за свій модуль.
    # Порядок реєстрації важливий і тепер керується всередині `register_general_handlers`.
    register_general_handlers(dp)
    # КЛЮЧОВЕ ПОКРАЩЕННЯ: Ми більше не передаємо `cmd_go` сюди.
    # Модуль `vision` тепер повністю незалежний.
    register_vision_handlers(dp)

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")
        
        # КРОК 3: ПОВІДОМЛЕННЯ АДМІНІСТРАТОРУ
        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                
                admin_message = "\n".join([
                    f"🤖 <b>MLBB IUI mini {bot_version} запущено!</b>",
                    "",
                    f"🆔 @{bot_info.username}",
                    f"⏰ {launch_time_kyiv}",
                    f"🔩 <b>Архітектурне оновлення:</b>",
                    "  • Впроваджено FSM для створення паті.",
                    "  • Модулі `vision` та `general` роз'єднано (decoupled).",
                    "  • Обробник помилок оновлено до стандарту aiogram 3.x.",
                    "🟢 Готовий до роботи!"
                ])
                
                await bot.send_message(str(ADMIN_USER_ID), admin_message, parse_mode=ParseMode.HTML)
                logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}")

        # КРОК 4: ЗАПУСК БОТА
        logger.info("Розпочинаю polling...")
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt).")
    except TelegramAPIError as e:
        logger.critical(f"Критична помилка Telegram API: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"Непередбачена критична помилка на рівні запуску: {e}", exc_info=True)
    finally:
        # КРОК 5: ГРАЦІЙНА ЗУПИНКА
        logger.info("🛑 Зупинка бота та закриття сесій...")
        if bot.session and not bot.session.closed:
            await bot.session.close()
            logger.info("Сесію HTTP клієнта успішно закрито.")
        logger.info("👋 Бот остаточно зупинено.")

if __name__ == "__main__":
    # Встановлюємо асинхронну точку входу
    asyncio.run(main())
