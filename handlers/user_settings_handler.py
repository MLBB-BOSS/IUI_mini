"""
Обробники для налаштувань користувача, таких як ввімкнення/вимкнення бота.
"""
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode

from database.crud import set_user_mute_status, get_user_by_telegram_id
from utils.cache_manager import clear_user_cache
from config import logger

settings_router = Router()

MUTE_MESSAGE = (
    "🔇 **Автоматичні відповіді вимкнено.**\n\n"
    "Я більше не буду реагувати на ваші повідомлення та зображення в цьому чаті.\n\n"
    "💡 *Щоб увімкнути мене знову, просто напишіть /unmute або дайте відповідь на будь-яке моє повідомлення.*"
)

UNMUTE_MESSAGE = (
    "🔊 **Приємно знову спілкуватися!**\n\n"
    "Автоматичні відповіді для вас знову увімкнено. "
    "Я готовий аналізувати, допомагати та брати участь у житті чату. Погнали! 🚀"
)

ERROR_MESSAGE = "🤔 Щось пішло не так. Спробуйте, будь ласка, пізніше."


@settings_router.message(Command("mute"))
async def cmd_mute(message: Message):
    """Обробник команди /mute для вимкнення автоматичних відповідей."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    logger.info(f"User {user_id} triggered /mute command.")

    # Перевіряємо, чи користувач взагалі є в базі
    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        await message.reply(
            "Спочатку вас потрібно зареєструвати. Будь ласка, використайте /profile, "
            "а потім ви зможете керувати налаштуваннями."
        )
        return

    success = await set_user_mute_status(user_id, is_muted=True)
    if success:
        await clear_user_cache(user_id)  # Інвалідація кешу
        await message.reply(MUTE_MESSAGE, parse_mode=ParseMode.HTML)
    else:
        await message.reply(ERROR_MESSAGE)


@settings_router.message(Command("unmute"))
async def cmd_unmute(message: Message):
    """Обробник команди /unmute для увімкнення автоматичних відповідей."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    logger.info(f"User {user_id} triggered /unmute command.")

    # Перевіряємо, чи користувач взагалі є в базі
    user_data = await get_user_by_telegram_id(user_id)
    if not user_data:
        # Якщо користувача немає, то він і так не "зам'ючений", нічого робити не треба
        await message.reply("Ви й так не були 'зам\'ючені', але дякую за команду! 😉")
        return

    success = await set_user_mute_status(user_id, is_muted=False)
    if success:
        await clear_user_cache(user_id)  # Інвалідація кешу
        await message.reply(UNMUTE_MESSAGE, parse_mode=ParseMode.HTML)
    else:
        await message.reply(ERROR_MESSAGE)


def register_settings_handlers(dp: Router):
    """Реєструє обробники налаштувань."""
    dp.include_router(settings_router)
    logger.info("✅ Обробники налаштувань користувача (/mute, /unmute) зареєстровано.")
