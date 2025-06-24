"""
Модуль для обробки загальних команд та подій, таких як /start, /help,
а також для централізованої обробки помилок.
"""
import logging
from aiogram import Dispatcher, types, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Update
from aiogram.exceptions import TelegramBadRequest

# Створюємо роутер для загальних обробників.
# Це дозволяє зберігати логіку модульною та чистою.
general_router = Router(name="general_router")

@general_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """
    Обробник команди /start.

    Вітає користувача, скидає його стан (FSM) на випадок,
    якщо він був у якомусь діалозі, та надає коротку інструкцію.
    """
    await state.clear()
    welcome_text = (
        "<b>Вітаю! Я GGenius, ваш персональний MLBB-аналітик.</b>\n\n"
        "Я тут, щоб допомогти вам розбирати матчі, аналізувати стратегії та покращувати вашу гру.\n\n"
        "🎮 <b>Що я вмію:</b>\n"
        "  • <b>Аналізувати скріншоти:</b> Надішліть мені скріншот післяматчевої статистики, і я зроблю детальний розбір.\n"
        "  • <b>Відповідати на запитання:</b> Використовуйте команду <code>/gemini</code> або просто згадайте мене в чаті, щоб поставити запитання.\n\n"
        "Для списку всіх команд, введіть /help."
    )
    await message.answer(welcome_text)


@general_router.message(Command(commands=["help"]))
async def cmd_help(message: Message):
    """
    Обробник команди /help.

    Надає розширену довідку щодо функціонала бота.
    """
    help_text = (
        "<b>Довідка по функціях GGenius:</b>\n\n"
        "<b>Аналіз зображень (Vision):</b>\n"
        "Просто надішліть зображення (скріншот) у чат. Для найкращого результату, додайте текстовий підпис із вашим запитанням. Наприклад: <i>\"Проаналізуй мій білд та запропонуй покращення.\"</i>\n\n"
        "<b>Пряма взаємодія з Gemini AI:</b>\n"
        "  • <b>Команда <code>/gemini</code>:</b> Почніть повідомлення з цієї команди, щоб поставити будь-яке запитання. Наприклад: <code>/gemini яка зараз мета для роумерів?</code>\n"
        "  • <b>Тригерні слова:</b> Бот автоматично відповість, якщо в повідомленні є слова 'gemini' або 'джеміні'.\n"
        "  • <b>Новий діалог:</b> Команда <code>/newchat</code> скидає історію вашого діалогу, що корисно, коли ви хочете обговорити нову тему.\n\n"
        "Звертайтеся з будь-якими питаннями щодо Mobile Legends!"
    )
    await message.answer(help_text)


async def cmd_go(message: types.Message, state: FSMContext):
    """
    Приклад реалізації функції `cmd_go`, яка передається в інші обробники.
    Її можна розширити для виконання специфічних дій.
    """
    # Ця функція передається як аргумент, тому її сигнатура важлива.
    # Логіка може бути будь-якою, наприклад, запуск певного сценарію FSM.
    logger.info(f"Користувач {message.from_user.id} викликав дію 'go'.")
    await message.reply("Дія 'go' в обробці...")


async def error_handler(update: Update, exception: Exception, bot: types.Bot):
    """
    Централізований обробник помилок.

    Логує всі винятки та сповіщає користувача про проблему.
    Це допомагає уникнути повного падіння бота через помилку в одному з обробників.
    """
    logger.error(f"Виникла помилка при обробці update: {exception}", exc_info=True)

    error_message = (
        "🔴 <b>Ой, щось пішло не так...</b>\n\n"
        "Сталася непередбачена помилка. Я вже надіслав звіт розробникам.\n"
        "Спробуйте, будь ласка, повторити свій запит трохи пізніше."
    )

    # Намагаємось надіслати повідомлення користувачу, якщо це можливо
    if update.message:
        try:
            await update.message.answer(error_message)
        except Exception as e:
            logger.error(f"Не вдалося навіть надіслати повідомлення про помилку: {e}")

    return True


def register_general_handlers(dp: Dispatcher):
    """
    Реєструє роутер із загальними обробниками у головному диспетчері.
    """
    dp.include_router(general_router)
    # Глобальний обробник помилок реєструється в main.py, що є гарною практикою.
    # dp.errors.register(error_handler)
