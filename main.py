"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.
Додано: Бета-функціонал GPT Vision.

Python 3.11+ | aiogram 3.19+ | OpenAI gpt-4.1 / gpt-4o
Author: MLBB-BOSS | Date: 2025-05-25
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
# NEW: FSMContext може знадобитися, якщо плануєш глобальні FSM обробники, хоча для підключення роутера не обов'язково
# from aiogram.fsm.context import FSMContext
# from aiogram.fsm.storage.memory import MemoryStorage # MemoryStorage є сховищем за замовчуванням

from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

# NEW: Імпорт роутера для GPT Vision Beta
# Переконайся, що директорія 'handlers' знаходиться на тому ж рівні, що й main.py,
# або налаштуй PYTHONPATH відповідно.
try:
    from handlers import vision_beta_handler
except ImportError as e:
    logging.error(f"Помилка імпорту vision_beta_handler: {e}. Переконайтеся, що файл handlers/vision_beta_handler.py існує.")
    vision_beta_handler = None # Для безпечного запуску, якщо файл відсутній

# === НАЛАШТУВАННЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(module)-15s | %(funcName)-20s | %(message)s" # MODIFIED: Додав module та funcName для кращого логування
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0")) # Залишаємо 0 як безпечне значення за замовчуванням

if not TELEGRAM_BOT_TOKEN: # MODIFIED: Розділив перевірки для чіткіших повідомлень
    logger.critical("❌ TELEGRAM_BOT_TOKEN не встановлено в .env файлі! Бот не може запуститися.")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN в .env файлі")

if not OPENAI_API_KEY:
    logger.warning("⚠️ OPENAI_API_KEY не встановлено в .env файлі! Функції GPT (текст та Vision) не працюватимуть.")
    # Дозволяємо запуск для можливості тестування інших частин, але GPT не працюватиме


class MLBBChatGPT:
    """
    Спеціалізований GPT асистент для MLBB з персоналізацією.
    Відповіді структуруються, оформлюються для ідеального вигляду в Telegram.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            logger.error("MLBBChatGPT ініціалізовано без API ключа.")
        self.api_key = api_key
        self.session: Optional[ClientSession] = None

    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=60), # MODIFIED: Збільшено загальний таймаут для потенційно довших запитів GPT
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """Створює розумний промпт для якісних відповідей."""
        current_hour = datetime.now().hour
        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

        # MODIFIED: Додав більше деталей до системного промпту для кращої відповіді
        return f"""
        Роль: Ти – IUI mini, експертний AI-асистент та доброзичливий порадник у світі Mobile Legends: Bang Bang.
        Твоя місія – надавати гравцю ({user_name}) чіткі, корисні та мотивуючі відповіді українською мовою.

        Стиль спілкування:
        1. Привітання: Завжди починай з теплого привітання, наприклад, "{greeting}, {user_name}! 👋"
        2. Емодзі: Активно використовуй доречні емодзі (🎮, 💡, 🚀, 🔥, 🦸, 🗺️, 🛡️, ⚔️, 📍, 💬, 💰, 🔄, 🤝, 🤔, 🎯, ✨, 💪), щоб зробити текст живішим.
        3. Звернення: Звертайся до користувача на ім'я ({user_name}).
        4. Тон: Дружній, підбадьорливий, як досвідчений тіммейт.
        5. Структура: Використовуй короткі абзаци, списки (•), жирний шрифт для акцентів (тільки через HTML <b>теги</b>).
        6. Обсяг: Намагайся відповідати лаконічно, але повно (до 200-250 слів).
        7. Мова: Виключно українська.

        Обмеження:
        - НЕ використовуй Markdown. ТІЛЬКИ HTML для форматування (<b>, <i>, <code>).
        - НЕ давай прямих порад щодо купівлі внутрішньоігрових предметів за реальні гроші.
        - НЕ генеруй відповіді, що порушують правила гри або етичні норми.
        - Якщо питання не стосується MLBB, ввічливо повідом про це і запропонуй повернутися до теми гри.

        Конкретні завдання (якщо релевантно до запиту {user_name}):
        - Пояснюй механіки, стратегії, оновлення, термінологію MLBB.
        - Допомагай з вибором героїв, ролей, аналізом мети.
        - Надавай поради щодо тактик, командної гри, індивідуальних навичок.
        - Розповідай про події, турніри (загальна інформація).

        Приклад форматування відповіді:
        "Привіт, {user_name}! ☀️
        Чудове питання про ротації! 🔄
        <b>Ключові моменти:</b>
        • Рання гра: допомога ліснику, контроль річки.
        • Середня гра: ганки, взяття веж.
        • Пізня гра: фокус на Лорді та командних боях.
        Пам'ятай про комунікацію з командою! 💬 Успіхів на полях бою! 🔥"

        Запит від {user_name}: "{user_query}"
        Твоя експертна відповідь:
        """

    def _beautify_response(self, text: str) -> str:
        """
        Оформлює текст GPT для Telegram: замінює markdown/заголовки, додає емодзі, відступи.
        Ця функція може бути спрощена, якщо системний промпт вже вимагає HTML.
        """
        # Спрощена версія, оскільки промпт вже націлений на HTML-подібне форматування
        # Основне очищення від можливих залишків Markdown, якщо модель їх додасть
        text = text.replace("**", "") # Прибираємо жирний Markdown
        text = text.replace("*", "")  # Прибираємо курсив Markdown
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE) # Списки
        text = re.sub(r"\n{3,}", "\n\n", text) # Зайві переноси
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Отримує якісну відповідь від GPT і оформлює її для Telegram.
        """
        if not self.api_key:
            logger.warning("Спроба викликати get_response без OpenAI API ключа.")
            return f"Вибач, {user_name}, сервіс тимчасово недоступний через проблеми з конфігурацією. 😔"

        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4o", # MODIFIED: Використовуємо новішу модель, якщо доступна
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 800, # MODIFIED: Збільшено для більш розгорнутих відповідей, якщо потрібно
            "temperature": 0.7, # MODIFIED: Трохи знижено для більшої передбачуваності
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1
        }

        try:
            if not self.session or self.session.closed: # NEW: Перевірка сесії
                logger.warning("Aiohttp сесія не активна. Спроба відновити.")
                # Це не найкраще місце для __aenter__, але для простоти міні-версії:
                self.session = ClientSession(
                    timeout=ClientTimeout(total=60),
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )

            async with self.session.post( # type: ignore
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"OpenAI API помилка: {response.status}, Текст: {error_text[:200]}")
                    return f"Вибач, {user_name}, виникла помилка під час звернення до AI ({response.status}) 😔 Спробуй ще раз!"

                result = await response.json()
                if not result.get("choices") or not result["choices"][0].get("message"):
                    logger.error(f"OpenAI API несподівана відповідь: {result}")
                    return f"Вибач, {user_name}, отримано дивну відповідь від AI. 🤯"

                gpt_text = result["choices"][0]["message"]["content"]
                return self._beautify_response(gpt_text)

        except asyncio.TimeoutError:
            logger.error(f"OpenAI API таймаут для запиту: {user_query[:50]}")
            return f"Вибач, {user_name}, запит до AI зайняв занадто багато часу. ⏳ Спробуй сформулювати його коротше."
        except Exception as e:
            logger.exception(f"GPT помилка під час обробки запиту від {user_name}: {e}")
            return f"Не зміг обробити запит, {user_name} 😕 Спробуй пізніше!"


bot = Bot(
    token=TELEGRAM_BOT_TOKEN, # type: ignore
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
# NEW: Ініціалізація Dispatcher (MemoryStorage використовується за замовчуванням)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Просте та ефективне привітання."""
    user_name = message.from_user.first_name if message.from_user else "друже" # MODIFIED: Безпечне отримання імені
    current_hour = datetime.now().hour

    if 5 <= current_hour < 12:
        greeting = "Доброго ранку"
        emoji = "🌅"
    elif 12 <= current_hour < 17:
        greeting = "Доброго дня"
        emoji = "☀️"
    elif 17 <= current_hour < 22:
        greeting = "Доброго вечора"
        emoji = "🌆"
    else:
        greeting = "Доброї ночі"
        emoji = "🌙"

    # MODIFIED: Додав згадку про нову функцію Vision Beta
    welcome_text = f"""
{greeting}, <b>{user_name}</b>! {emoji}

🎮 Вітаю в MLBB IUI mini!

Я - твій персональний експерт по Mobile Legends Bang Bang, готовий допомогти з будь-якими питаннями про гру!

<b>💡 Як користуватися (текстові запити):</b>
Просто напиши своє питання після команди /go

<b>🚀 Приклади текстових запитів:</b>
• <code>/go соло стратегії для швидкого ранк-апу</code>
• <code>/go дуо тактики для доміну в лейті</code>
• <code>/go тріо комбо для командних боїв</code>
• <code>/go як читати карту та контролювати об'єкти</code>

✨ <b>НОВИНКА! Бета-версія аналізу зображень!</b> ✨
Надішли команду /vision_beta, щоб я спробував проаналізувати твій скріншот з гри!

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    try:
        await message.answer(welcome_text)
        logger.info(f"✅ Привітання для {user_name} (ID: {message.from_user.id if message.from_user else 'N/A'})")
    except TelegramAPIError as e:
        logger.error(f"Помилка відправки привітання для {user_name}: {e}")


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """Головна функція - якісне спілкування через GPT з красивим оформленням."""
    if not message.from_user: # NEW: Перевірка наявності користувача
        logger.warning("Повідомлення без користувача в cmd_go.")
        return

    user_name = message.from_user.first_name
    user_query = message.text.replace("/go", "", 1).strip() if message.text else "" # MODIFIED: Безпечне отримання тексту

    if not user_query:
        await message.reply(
            f"Привіт, <b>{user_name}</b>! 👋\n\n"
            "Напиши своє питання після /go\n"
            "<b>Приклади:</b>\n"
            "• /go соло стратегії для швидкого ранк-апу\n"
            "• /go як читати карту та контролювати об'єкти"
        )
        return

    thinking_messages = [
        f"🤔 {user_name}, думаю над твоїм питанням...",
        f"🧠 Аналізую запит, {user_name}!",
        f"⚡ Готую експертну відповідь для тебе!",
        f"🎯 {user_name}, шукаю найкращі поради!"
    ]
    # MODIFIED: Використовуємо message.chat.id для відповіді, якщо раптом message.reply не спрацює (хоча малоймовірно)
    thinking_msg = await bot.send_message(
        message.chat.id,
        thinking_messages[hash(user_query) % len(thinking_messages)]
    )

    start_time = time.time()

    # NEW: Перевірка наявності API ключа перед створенням екземпляру
    if not OPENAI_API_KEY:
        logger.error("OpenAI API ключ не знайдено для MLBBChatGPT.")
        await thinking_msg.edit_text(f"Вибач, {user_name}, сервіс AI тимчасово недоступний. 🛠️")
        return

    async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
        response = await gpt.get_response(user_name, user_query)

    processing_time = time.time() - start_time
    logger.info(f"Запит від {user_name} (ID: {message.from_user.id}): '{user_query[:50]}...' оброблено за {processing_time:.2f}s")


    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ Час обробки: {processing_time:.2f}с</i>"

    try:
        await thinking_msg.edit_text(f"{response}{admin_info}")
        logger.info(f"📤 Відповідь для {user_name} успішно відредаговано.")
    except TelegramAPIError as e:
        logger.warning(f"Не вдалося відредагувати повідомлення 'думаю...' (ID: {thinking_msg.message_id}). Помилка: {e}. Надсилаю нове.")
        try:
            await message.answer(f"{response}{admin_info}") # MODIFIED: Використовуємо message.answer як запасний варіант
            logger.info(f"📤 Відповідь для {user_name} надіслано новим повідомленням.")
        except TelegramAPIError as e2:
            logger.error(f"Не вдалося надіслати відповідь навіть новим повідомленням для {user_name}. Помилка: {e2}")


# MODIFIED: Зробив обробник помилок більш інформативним
@dp.errors()
async def error_handler(update_event, exception: Exception) -> bool: # type: ignore
    """
    Глобальний обробник помилок. Логує помилку та повідомляє користувача.
    """
    logger.error(f"🚨 Глобальна помилка в Dispatcher: {exception}", exc_info=True)

    message_to_reply: Optional[Message] = None
    if hasattr(update_event, 'message') and update_event.message:
        message_to_reply = update_event.message
    elif hasattr(update_event, 'callback_query') and update_event.callback_query and update_event.callback_query.message:
        message_to_reply = update_event.callback_query.message

    if message_to_reply:
        user_name = message_to_reply.from_user.first_name if message_to_reply.from_user else "друже"
        try:
            await message_to_reply.answer(
                f"Ой, {user_name}, щось пішло не так... ⚙️ Наші технічні спеціалісти вже повідомлені.\n"
                "Спробуйте, будь ласка, повторити свій запит трохи пізніше."
            )
        except Exception as e_reply:
            logger.error(f"🚨 Не вдалося надіслати повідомлення про помилку користувачу: {e_reply}")
    return True # Позначаємо, що помилка оброблена


async def main() -> None:
    """Запуск бота."""
    logger.info("🚀 Запуск MLBB IUI mini Bot...")

    # NEW: Підключення роутера для Vision Beta
    if vision_beta_handler and hasattr(vision_beta_handler, 'router'):
        dp.include_router(vision_beta_handler.router)
        logger.info("✅ Vision Beta Handler підключено до диспетчера.")
    else:
        logger.warning("⚠️ Vision Beta Handler не підключено (не знайдено або помилка імпорту).")

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} (MLBB IUI mini) готовий!")

        if ADMIN_USER_ID != 0: # MODIFIED: Перевірка чи ADMIN_USER_ID встановлено
            try:
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini Bot запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (UTC: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')})\n"
                    f"{'🔮 Функція Vision Beta активна!' if vision_beta_handler else ' Функція Vision Beta НЕ активна.'}\n"
                    f"🟢 Готовий до роботи!"
                )
            except TelegramAPIError as e_admin:
                logger.warning(f"⚠️ Не вдалося надіслати повідомлення адміну (ID: {ADMIN_USER_ID}): {e_admin}")
            except Exception as e_admin_other:
                 logger.warning(f"⚠️ Не вдалося надіслати повідомлення адміну (невідома помилка): {e_admin_other}")


        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()) # MODIFIED: Додав allowed_updates

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (Ctrl+C).")
    except TelegramAPIError as e:
        logger.critical(f"💥 Критична помилка Telegram API під час запуску: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"💥 Критична неперехоплена помилка: {e}", exc_info=True)
    finally:
        logger.info("🔌 Починаю процедуру зупинки бота...")
        if bot.session and not bot.session.closed: # MODIFIED: Перевірка перед закриттям
            await bot.session.close()
            logger.info("🔌 Aiohttp сесію бота закрито.")
        await dp.storage.close() # NEW: Закриття сховища FSM
        logger.info("🛑 Роботу бота коректно завершено.")


if __name__ == "__main__":
    # NEW: Встановлення політики циклу подій для Windows, якщо потрібно (для сумісності)
    # if os.name == 'nt':
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
