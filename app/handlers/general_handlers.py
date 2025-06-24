import logging
from aiogram import Router, Bot, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ErrorEvent
from aiogram.exceptions import TelegramAPIError
from config import ADMIN_USER_ID

# Створюємо роутер для загальних обробників. Це дозволяє групувати логіку.
general_router = Router(name="general_router")
logger = logging.getLogger(__name__)

# Ця функція не потрібна, якщо ми імпортуємо роутер напряму в main.py,
# але я залишаю її, якщо ви використовуєте такий патерн в інших місцях.
def register_general_handlers(dp):
    dp.include_router(general_router)

@general_router.message(CommandStart())
async def cmd_start(message: types.Message):
    """
    Обробник команди /start. Вітає користувача.
    """
    start_message = (
        "<b>Вітаю! Я MLBB IUI mini.</b>\n\n"
        "Ваш персональний асистент для аналізу ігрових результатів у Mobile Legends: Bang Bang.\n\n"
        "<b>Що я вмію:</b>\n"
        "► Аналізувати скріншоти з результатами матчів.\n"
        "► Надавати поради щодо збірок та стратегій.\n"
        "► Відповідати на питання про гру.\n\n"
        "Просто надішліть мені скріншот, і я почну аналіз!"
    )
    await message.answer(start_message)

@general_router.message(Command("help"))
async def cmd_help(message: types.Message):
    """
    Обробник команди /help. Надає довідкову інформацію.
    """
    help_text = (
        "<b>Довідка по командам:</b>\n\n"
        "<code>/start</code> - Перезапустити бота та отримати вітальне повідомлення.\n"
        "<code>/help</code> - Показати це повідомлення.\n\n"
        "<b>Основна функціональність:</b>\n"
        "Просто надішліть зображення (скріншот) з гри в цей чат. Я автоматично його оброблю та надам детальний аналіз."
    )
    await message.answer(help_text)

async def cmd_go(message: types.Message, **data):
    """
    Заглушка для логіки команди /go.
    Ця функція, ймовірно, викликається з іншого обробника (наприклад, vision_handler),
    тому вона не декорована як обробник повідомлення.
    """
    await message.reply("Команда /go наразі в розробці.")

async def general_error_handler(event: ErrorEvent, bot: Bot):
    """
    Централізований обробник помилок для aiogram 3.x.
    Логує всі винятки та сповіщає користувача/адміністратора.

    Args:
        event (ErrorEvent): Об'єкт, що містить оновлення та виняток.
        bot (Bot): Екземпляр бота, переданий при реєстрації.
    """
    logger.error(f"Помилка в обробнику: {event.exception}", exc_info=True)

    user_message = "🔴 <b>Сталася помилка</b>\n\nНа жаль, під час обробки вашого запиту виникла проблема. Спробуйте, будь ласка, пізніше."
    chat_id = event.update.message.chat.id if event.update.message else None

    if chat_id:
        try:
            await bot.send_message(chat_id, user_message)
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення про помилку в чат {chat_id}: {e}")

    # Надсилаємо детальне повідомлення про помилку адміністратору
    if ADMIN_USER_ID:
        try:
            admin_message = (
                f"⚠️ <b>Зафіксовано помилку в боті!</b>\n\n"
                f"<b>Тип помилки:</b> <code>{type(event.exception).__name__}</code>\n"
                f"<b>Повідомлення:</b> <code>{event.exception}</code>\n\n"
                f"<b>Update ID:</b> <code>{event.update.update_id}</code>"
            )
            await bot.send_message(ADMIN_USER_ID, admin_message)
        except Exception as e:
            logger.error(f"Не вдалося надіслати звіт про помилку адміну {ADMIN_USER_ID}: {e}")
