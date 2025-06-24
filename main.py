import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage # <-- 1. Імпорт сховища для FSM
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# Імпорти з проєкту
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID, logger
# Імпортуємо роутери та функції реєстрації
from app.handlers.general_handlers import register_general_handlers, error_handler as general_error_handler
from app.handlers.vision_handlers import register_vision_handlers
from app.handlers.gemini_handler import gemini_router # <-- 2. Імпорт роутера Gemini
# Імпортуємо cmd_go для передачі в vision_handlers
from app.handlers.general_handlers import cmd_go


async def main() -> None:
    """
    Головна асинхронна функція для ініціалізації та запуску Telegram-бота.
    Вона налаштовує логування, конфігурує бота та диспетчер,
    реєструє обробники повідомлень та помилок, і запускає polling.
    """
    bot_version = "v3.0.0 (інтеграція Gemini)"
    logger.info(f"🚀 Запуск MLBB IUI mini {bot_version}... (PID: {os.getpid()})")

    # Ініціалізація сховища для FSM. MemoryStorage підходить для розробки.
    # Для production рекомендується використовувати RedisStorage.
    storage = MemoryStorage()

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Передаємо сховище в диспетчер
    dp = Dispatcher(storage=storage)

    # Реєстрація роутерів з різних модулів
    # Такий підхід робить архітектуру чистою та модульною
    register_general_handlers(dp)
    register_vision_handlers(dp, cmd_go_handler_func=cmd_go)
    dp.include_router(gemini_router) # <-- 3. Реєстрація роутера Gemini

    # Реєстрація глобального обробника помилок.
    # Явний виклик register є більш надійним, ніж декоратор у головному файлі.
    dp.errors.register(general_error_handler, exception=Exception)

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (ID: {bot_info.id}) успішно авторизований!")

        if ADMIN_USER_ID:
            await notify_admin_on_startup(bot, bot_info, bot_version)

        logger.info("Розпочинаю polling...")
        # Видаляємо необроблені оновлення, щоб не відповідати на старі повідомлення після перезапуску
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
        await dp.storage.close() # Коректно закриваємо сховище
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
            "🔩 <b>Активні моделі:</b>",
            "  • <b>Vision (OpenAI):</b> <code>gpt-4o-mini</code>",
            "  • <b>Text/Analysis (Google):</b> <code>gemini-1.5-flash</code>",
            "---",
            "✨ <b>Ключове оновлення:</b>",
            "  • Інтегровано модуль <b>Google Gemini</b> для аналізу тексту та зображень.",
            "  • Додано команди <code>/start</code>, <code>/help</code>, <code>/newchat</code> для Gemini.",
            "  • Бот тепер реагує на тригерні слова та фото з підписами.",
            "  • Впроваджено FSM для ведення історії діалогів.",
            "🟢 Готовий до роботи!"
        ]
        admin_message = "\n".join(admin_message_lines)

        await bot.send_message(str(ADMIN_USER_ID), admin_message, parse_mode=ParseMode.HTML)
        logger.info(f"Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
    except Exception as e:
        logger.warning(f"Не вдалося надіслати повідомлення про запуск адміну (ID: {ADMIN_USER_ID}): {e}", exc_info=True)


if __name__ == "__main__":
    # Налаштування логування для aiogram, щоб бачити детальніші помилки
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    asyncio.run(main())
