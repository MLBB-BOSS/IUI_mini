"""
MLBB IUI mini - Мінімалістична версія з максимальною якістю GPT спілкування.
Фокус на одній функції: розумні відповіді про Mobile Legends Bang Bang.

Python 3.11+ | aiogram 3.19+ | OpenAI gpt-4.1
Author: MLBB-BOSS | Date: 2025-05-25
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

# === НАЛАШТУВАННЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")


class MLBBChatGPT:
    """
    Спеціалізований GPT асистент для MLBB з персоналізацією.
    Відповіді структуруються, оформлюються для ідеального вигляду в Telegram.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None

    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=30),
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _create_smart_prompt(self, user_name: str, user_query: str) -> str:
        """
        🚀 РЕВОЛЮЦІЙНИЙ ПРОМПТ v2.1 - Акцент на конкретних героях та комбо!
        """
        kyiv_tz = timezone(timedelta(hours=3))  # UTC+3 для України
        current_time_kyiv = datetime.now(kyiv_tz)
        current_hour = current_time_kyiv.hour

        greeting = "Доброго ранку" if 5 <= current_hour < 12 else \
            "Доброго дня" if 12 <= current_hour < 17 else \
            "Доброго вечора" if 17 <= current_hour < 22 else "Доброї ночі"

        # Оновлений промпт v2.1
        return f"""# СИСТЕМА: MLBB ЕКСПЕРТ IUI v2.1 🎮

## ПРОФІЛЬ АСИСТЕНТА
Ти - IUI, найкращий AI-експерт Mobile Legends Bang Bang в Україні з 7+ років досвіду.
Твоя місія: надавати гравцю {user_name} максимально корисні, точні, конкретні та мотивуючі відповіді.

## КОНТЕКСТ СПІЛКУВАННЯ
- Користувач: {user_name}
- Час: {greeting.lower()} ({current_time_kyiv.strftime('%H:%M')} за Києвом)
- Платформа: Telegram (підтримує HTML)
- Мова: виключно українська

## СТАНДАРТИ ЯКОСТІ ВІДПОВІДЕЙ

### 🎯 ОБОВ'ЯЗКОВА СТРУКТУРА:
1. **Привітання**: "{greeting}, {user_name}! 👋"
2. **Основна відповідь**: конкретна інформація. 
   - Якщо запит стосується стратегій, ролей, вибору героїв або гри на певній лінії (наприклад, "як грати на експ лінії", "порадь героя для міду", "стратегія для підняття рангу"), ОБОВ'ЯЗКОВО наведи 2-3 приклади актуальних героїв (наприклад, 🦸‍♂️ <b>Ю Чжун</b>, 🦸‍♀️ <b>Есмеральда</b>). 
   - Коротко поясни, чому саме ці герої підходять для описаної ситуації (їхні сильні сторони, роль у команді).
   - За можливості, запропонуй ефективні комбінації цих героїв з іншими або опиши їхню синергію.
3. **Практичні поради**: що робити прямо зараз, базуючись на наданих прикладах героїв або загальних тактиках.
4. **Мотивація**: підбадьорення до дій та експериментів з героями.

### 📝 ФОРМАТУВАННЯ:
- Використовуй ТІЛЬКИ HTML теги: <b>жирний</b>, <i>курсив</i>, <code>код</code>.
- Списки через "•" (з пробілом після). Використовуй підпункти (наприклад, з відступом та іншим маркером), якщо це покращує читабельність при описі героїв.
- Максимум 250-300 слів, структурно та лаконічно.
- Обов'язкові емодзі для кращого сприйняття (🦸‍♂️ для героїв, 💡 для порад, 🤝 для комбо).

### 🎮 ЕКСПЕРТИЗА MLBB:
- **Герої**: механіки, ролі, актуальні контрпіки, сильні герої для поточної мети. ЗАВЖДИ пропонуй конкретні приклади героїв для запитуваних сценаріїв з коротким обґрунтуванням.
- **Стратегії**: лейн-менеджмент, об'єктний контроль, тімфайти, макро-гра.
- **Ранкінг**: тактики для підняття рангу, адаптація під різні ранги.
- **Психологія**: комунікація, тільт-контроль, командний дух.
- **Поточний патч**: враховуй актуальні тренди, зміни, оновлення при рекомендації героїв.

### ❌ ЗАБОРОНЕНО:
- Markdown форматування.
- Конкретні білди (предмети/емблеми) – вони швидко застарівають. Замість цього, фокусуйся на стилі гри героя та його ролі.
- Довгі суцільні тексти без структури та абзаців.
- Відповіді не українською мовою.

### 🧠 ПРИНЦИПИ МИСЛЕННЯ:
1. **Аналізуй запит**: що насправді хоче знати {user_name}? Яку проблему він намагається вирішити?
2. **Конкретика перш за все**: Замість загальних фраз – конкретні герої та поради.
3. **Практичність**: давай поради, які можна одразу застосувати в грі.
4. **Адаптивність**: враховуй можливий рівень гравця (якщо це можна зрозуміти з контексту).
5. **Позитивність**: мотивуй та надихай на покращення гри.

## ПРИКЛАД ІДЕАЛЬНОЇ ВІДПОВІДІ (на запит "як грати на експ лінії"):
"{greeting}, {user_name}! 👋

Гра на експ лінії – це твій шанс стати опорою команди та контролювати темп ранньої гри! 🛡️

🦸‍♂️ <b>Рекомендовані герої для експ лінії (поточна мета):</b>
• <b>Ю Чжун (Yuzhong):</b> Дуже сильний в 1на1 завдяки своїй пасивній здібності та можливості відхілу. Чудово пушить лінію та має величезний імпакт у масових бійках своїм ультімейтом (трансформація в дракона). <i>Ідеальний для агресивної гри та домінації на лінії.</i>
• <b>Есмеральда (Esmeralda):</b> Неймовірна виживаність за рахунок поглинання щитів ворогів та перетворення їх на власні. Може довго стояти на лінії, ефективно харасити супротивника та брати участь у захопленні об'єктів (наприклад, Черепахи). <i>Чудовий вибір проти героїв, які покладаються на щити.</i>
• <b>Глу (Gloo):</b> Унікальний танк/боєць, що здатен розділяти ворожу команду та створювати хаос. Його ультімейт дозволяє прикріпитися до найбільш небезпечного ворога, контролюючи його та завдаючи шкоди. <i>Відмінно підходить для командних стратегій та контролю ключових цілей.</i>

💡 <b>Ключові поради для експ лайнера:</b>
• <b>Пріоритет на фарм:</b> Не пропускай хвилі міньйонів, це твоє золото та досвід.
• <b>Контроль карти:</b> Після отримання 2-3 рівня активно слідкуй за переміщенням ворожого лісника та гравця центральної лінії. Будь готовий допомогти своїй команді.
• <b>Об'єкти – твоя ціль:</b> Допомагай команді з Черепахою та Лордом. Ініціюй пуш лінії, коли це безпечно та доцільно.
• <b>Ініціація або захист:</b> Залежно від обраного героя та ситуації в грі, ти можеш бути тим, хто починає тімфайт, або тим, хто захищає своїх союзників.

🤝 <b>Приклад синергії/комбінації:</b>
Якщо у твоїй команді є герой з масовим контролем, наприклад, <i>Атлас</i> або <i>Тігріл</i>, герої як <i>Ю Чжун</i> або <i>Лапу-Лапу</i> на експ лінії можуть максимально реалізувати свій потенціал шкоди після вдалої ініціації від танка. Наприклад, ультімейт Атласа збирає ворогів, а Ю Чжун влітає в них драконом.

<b>Твій успіх на експ лінії</b> – це поєднання терпіння, глибокого розуміння карти та вміння адаптувати вибір героя під конкретну ситуацію та склад команди. Не бійся експериментувати з різними героями! Готовий домінувати? 🚀"

## ЗАПИТ ВІД {user_name}: "{user_query}"

Твоя експертна відповідь (дотримуйся ВСІХ стандартів вище, особливо щодо конкретних прикладів героїв):"""

    def _beautify_response(self, text: str) -> str:
        """
        Оформлює текст GPT для Telegram: замінює markdown/заголовки, додає емодзі, відступи.
        """
        # Емодзі для різних категорій MLBB
        header_emojis = {
            "карти": "🗺️", "об'єктів": "🛡️", "тактика": "⚔️", "позиція": "📍",
            "комунікація": "💬", "героя": "🦸", "героїв": "🦸‍♂️🦸‍♀️", "фарм": "💰", "ротація": "🔄",
            "командна гра": "🤝", "комбінації": "🤝", "синергія": "✨", "ранк": "🏆", 
            "стратегі": "🎯", "мета": "🔥", "поточна мета": "📊",
            "навички": "📈", "тайминг": "⏰", "контроль": "🎮", "пуш": "⬆️",
            "поради": "💡", "ключові поради": "💡"
        }

        def replace_header(match):
            header_text = match.group(1).strip(": ").capitalize()
            # Спробуємо знайти більш точний емодзі
            best_emoji = "💡" # дефолтний емодзі для загальних заголовків
            
            # Спочатку для більш конкретних ключів
            specific_keys = ["героїв", "героя", "комбінації", "синергія", "ключові поради", "поточна мета"]
            for key in specific_keys:
                if key in header_text.lower():
                    best_emoji = header_emojis.get(key, best_emoji)
                    break
            else: # Якщо не знайдено серед специфічних, шукаємо серед загальних
                for key, emj in header_emojis.items():
                    if key in header_text.lower():
                        best_emoji = emj
                        break
            
            return f"\n\n{best_emoji} <b>{header_text}</b>:"

        # Замінюємо markdown заголовки на емодзі+жирний
        text = re.sub(r"^#{2,3}\s*(.+)", replace_header, text, flags=re.MULTILINE)
        text = re.sub(r"^\*\*(.+?)\*\*[:\s]*", replace_header, text, flags=re.MULTILINE) # Для **Заголовок:**
        text = re.sub(r"^<b>(.+?)</b>[:\s]*", lambda m: replace_header(m) if ':' in m.group(0) else m.group(0), text, flags=re.MULTILINE) # Для <b>Заголовок</b>:

        # Списки на "• "
        text = re.sub(r"^\s*[\-\*]\s+", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*•\s+-\s+", "  ◦ ", text, flags=re.MULTILINE) # для підпунктів типу "• - підпункт"
        
        # Прибираємо зайві переноси рядків
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Очищення від markdown залишків (якщо GPT все ж їх додасть)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
        
        return text.strip()

    async def get_response(self, user_name: str, user_query: str) -> str:
        """
        Отримує якісну відповідь від GPT і оформлює її для Telegram.
        """
        system_prompt = self._create_smart_prompt(user_name, user_query)
        payload = {
            "model": "gpt-4.1", # Або "gpt-4.1" якщо це псевдонім для новішої моделі
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 700, # Трохи збільшимо, так як відповіді стануть детальнішими
            "temperature": 0.75, # Зменшимо трохи для більшої точності з конкретними героями
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.2 # Трохи збільшимо, щоб стимулювати різноманітність героїв
        }

        try:
            if not self.session or self.session.closed:
                # Перестворюємо сесію, якщо вона закрита або не існує
                self.session = ClientSession(
                    timeout=ClientTimeout(total=45), # Трохи збільшимо таймаут
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )

            async with self.session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"OpenAI API помилка: {response.status} - {error_text}")
                    return f"Вибач, {user_name}, виникли технічні проблеми з доступом до ШІ 😔 (код: {response.status}). Спробуй, будь ласка, повторити запит трохи пізніше!"

                result = await response.json()
                
                if not result.get("choices") or not result["choices"][0].get("message") or not result["choices"][0]["message"].get("content"):
                    logger.error(f"OpenAI API помилка: несподівана структура відповіді - {result}")
                    return f"Вибач, {user_name}, ШІ повернув несподівану відповідь 🤯. Спробуй переформулювати запит."

                gpt_text = result["choices"][0]["message"]["content"]
                return self._beautify_response(gpt_text)

        except asyncio.TimeoutError:
            logger.error(f"OpenAI API Timeout помилка для запиту: {user_query}")
            return f"Вибач, {user_name}, запит до ШІ зайняв занадто багато часу ⏳. Спробуй ще раз!"
        except Exception as e:
            logger.exception(f"Загальна GPT помилка: {e}")
            return f"Не вдалося обробити твій запит, {user_name} 😕 Спробуй, будь ласка, пізніше!"


bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Просте та ефективне привітання."""
    user_name = message.from_user.first_name
    
    kyiv_tz = timezone(timedelta(hours=3))
    current_time_kyiv = datetime.now(kyiv_tz)
    current_hour = current_time_kyiv.hour

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

    welcome_text = f"""
{greeting}, <b>{user_name}</b>! {emoji}

🎮 Вітаю в MLBB IUI mini v2.1!

Я - твій персональний експерт по Mobile Legends Bang Bang, готовий допомогти з будь-якими питаннями про гру, надаючи конкретні поради та приклади героїв!

<b>💡 Як користуватися:</b>
Просто напиши своє питання після команди /go

<b>🚀 Приклади запитів:</b>
• <code>/go як грати на експ лінії проти бійців</code>
• <code>/go порадь сильних магів для підняття рангу соло</code>
• <code>/go найкращі комбінації героїв для командних боїв 5на5</code>
• <code>/go як ефективно контролювати карту та об'єкти граючи за лісника</code>

<b>🔥 Покращення v2.1:</b>
• Відповіді тепер включають конкретні приклади героїв!
• Поради стали більш практичними та менш "сухими".
• Акцент на актуальній меті та синергії героїв.

Готовий стати твоїм найкращим MLBB тіммейтом! 💪✨
"""
    await message.answer(welcome_text)
    logger.info(f"✅ Привітання для {user_name} (v2.1)")


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """Головна функція - якісне спілкування через GPT з красивим оформленням."""
    user_name = message.from_user.first_name
    user_query = message.text.replace("/go", "", 1).strip()

    if not user_query:
        await message.reply(
            f"Привіт, <b>{user_name}</b>! 👋\n\n"
            "Напиши своє питання після /go, і я спробую дати конкретні поради з прикладами героїв!\n"
            "<b>Приклади:</b>\n"
            "• /go стратегії для швидкого ранк-апу на стрільцях\n"
            "• /go яких героїв обрати для домінації на міді"
        )
        return

    thinking_messages = [
        f"🤔 {user_name}, аналізую твій запит та підбираю героїв...",
        f"🧠 Обробляю інформацію, {user_name}, щоб дати кращі поради!",
        f"⚡ Готую експертну відповідь з прикладами спеціально для тебе!",
        f"🎯 {user_name}, шукаю найефективніших героїв та стратегії для тебе!"
    ]

    thinking_msg = await message.reply(
        thinking_messages[hash(user_query + str(time.time())) % len(thinking_messages)]
    )

    start_time = time.time()

    # Створюємо екземпляр MLBBChatGPT тут, щоб сесія була активна для запиту
    async with MLBBChatGPT(OPENAI_API_KEY) as gpt:
        response_text = await gpt.get_response(user_name, user_query)

    processing_time = time.time() - start_time

    admin_info = ""
    if message.from_user.id == ADMIN_USER_ID:
        admin_info = f"\n\n<i>⏱ {processing_time:.2f}с | v2.1 Enhanced GPT-4T</i>"

    try:
        await thinking_msg.edit_text(f"{response_text}{admin_info}")
        logger.info(f"📤 Відповідь для {user_name} ({processing_time:.2f}s): Запит - '{user_query}'")
    except TelegramAPIError as e:
        logger.error(f"Telegram API помилка при редагуванні повідомлення: {e}. Спроба надіслати новим.")
        try:
            await message.reply(f"{response_text}{admin_info}")
            logger.info(f"📤 Відповідь для {user_name} (надіслано новим повідомленням після помилки редагування)")
        except Exception as final_e:
            logger.error(f"Не вдалося надіслати відповідь навіть новим повідомленням: {final_e}")
            await message.reply(f"Вибач, {user_name}, сталася помилка при відображенні відповіді. Спробуй ще раз.")


@dp.errors()
async def error_handler(update_event, exception: Exception):
    logger.error(f"🚨 Загальна помилка в обробнику: {exception} для update: {update_event}", exc_info=True)
    
    chat_id = None
    user_name = "друже"

    if hasattr(update_event, 'message') and update_event.message:
        chat_id = update_event.message.chat.id
        if update_event.message.from_user:
            user_name = update_event.message.from_user.first_name
    elif hasattr(update_event, 'callback_query') and update_event.callback_query:
        chat_id = update_event.callback_query.message.chat.id
        if update_event.callback_query.from_user:
            user_name = update_event.callback_query.from_user.first_name
    
    error_message_text = f"Вибач, {user_name}, сталася непередбачена помилка 😔\nСпробуй, будь ласка, ще раз через хвилину!"
    
    if chat_id:
        try:
            await bot.send_message(chat_id, error_message_text)
        except Exception as e:
            logger.error(f"🚨 Не вдалося надіслати повідомлення про помилку користувачу {user_name} в чат {chat_id}: {e}")
    else:
        logger.warning("🚨 Помилка сталася, але не вдалося визначити chat_id для відповіді.")


async def main() -> None:
    """Запуск бота."""
    logger.info("🚀 Запуск MLBB IUI mini v2.1...")

    # Створюємо сесію для бота один раз при старті
    # bot._session = ClientSession() # Це застарілий спосіб, краще через default bot properties або контекстний менеджер

    try:
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} готовий!")

        if ADMIN_USER_ID:
            try:
                kyiv_tz = timezone(timedelta(hours=3))
                launch_time_kyiv = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB IUI mini v2.1 запущено!</b>\n\n"
                    f"🆔 @{bot_info.username}\n"
                    f"⏰ {launch_time_kyiv}\n"
                    f"🎯 <b>Промпт v2.1 активний (з акцентом на героях)!</b>\n"
                    f"🟢 Готовий до роботи!"
                )
                logger.info(f"ℹ️ Повідомлення про запуск надіслано адміну ID: {ADMIN_USER_ID}")
            except Exception as e:
                logger.warning(f"⚠️ Не вдалося надіслати повідомлення про запуск адміну: {e}")

        # Починаємо обробку апдейтів
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (KeyboardInterrupt)")
    except TelegramAPIError as e:
        logger.critical(f"💥 Критична помилка Telegram API при запуску: {e}")
    except Exception as e:
        logger.critical(f"💥 Критична помилка при запуску: {e}", exc_info=True)
    finally:
        logger.info("🛑 Закриття сесій...")
        # Закриваємо сесію Dispatcher'а (якщо вона була створена явно, тут dp сам керує)
        # Закриваємо сесію бота
        if bot.session and not bot.session.closed:
            await bot.session.close()
            logger.info("Сесію бота закрито.")
        # if MLBBChatGPT.instance and MLBBChatGPT.instance.session and not MLBBChatGPT.instance.session.closed:
        #     await MLBBChatGPT.instance.session.close() # Якщо б сесія була частиною класу MLBBChatGPT як синглтон
        #     logger.info("Сесію MLBBChatGPT закрито.")
        logger.info("👋 Бот остаточно зупинено.")


if __name__ == "__main__":
    asyncio.run(main())
