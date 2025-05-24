"""
Розширена асинхронна версія Telegram-бота для MLBB-спільноти.
Інтеграція GPT з персоналізацією, контекстом та розширеним функціоналом.
Python 3.11+ | aiogram 3.19+ | OpenAI API
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, User, Chat, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

# --- Enhanced Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("mlbb_bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
load_dotenv()

TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

# Validation
for var_name, var_value in [
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("OPENAI_API_KEY", OPENAI_API_KEY)
]:
    if not var_value:
        logger.error(f"{var_name} не встановлено в environment variables!")
        raise RuntimeError(f"{var_name} is required.")

__all__ = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "ADMIN_USER_ID"]


@dataclass
class UserProfile:
    """Профіль користувача для персоналізації."""
    user_id: int
    first_name: str
    username: Optional[str] = None
    last_name: Optional[str] = None
    language_code: Optional[str] = "uk"
    is_premium: bool = False
    join_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    favorite_heroes: List[str] = field(default_factory=list)
    mlbb_rank: Optional[str] = None


@dataclass
class ChatContext:
    """Контекст чату для кращого розуміння GPT."""
    chat_id: int
    chat_type: str
    title: Optional[str] = None
    member_count: int = 0
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MLBBDatabase:
    """Простий in-memory storage для користувачів та контексту."""
    
    def __init__(self) -> None:
        self.users: Dict[int, UserProfile] = {}
        self.chats: Dict[int, ChatContext] = {}
        logger.info("📊 MLBB Database ініціалізовано")
    
    def get_or_create_user(self, user: User) -> UserProfile:
        """Отримує або створює профіль користувача."""
        if user.id not in self.users:
            self.users[user.id] = UserProfile(
                user_id=user.id,
                first_name=user.first_name,
                username=user.username,
                last_name=user.last_name,
                language_code=user.language_code,
                is_premium=user.is_premium or False
            )
            logger.info(f"👤 Створено новий профіль для {user.first_name}")
        
        # Оновлюємо дані при кожному зверненні
        profile = self.users[user.id]
        profile.first_name = user.first_name
        profile.username = user.username
        profile.last_name = user.last_name
        profile.message_count += 1
        
        return profile
    
    def get_or_create_chat(self, chat: Chat) -> ChatContext:
        """Отримує або створює контекст чату."""
        if chat.id not in self.chats:
            self.chats[chat.id] = ChatContext(
                chat_id=chat.id,
                chat_type=chat.type,
                title=chat.title
            )
            logger.info(f"💬 Створено контекст для чату: {chat.title or chat.id}")
        
        context = self.chats[chat.id]
        context.last_activity = datetime.now(timezone.utc)
        return context


class MLBBAssistant:
    """Розумний асистент для MLBB з персоналізацією."""
    
    MLBB_HEROES = [
        "Alucard", "Miya", "Saber", "Alice", "Nana", "Tigreal", "Akai", "Franco",
        "Bane", "Bruno", "Clint", "Rafaela", "Eudora", "Zilong", "Fanny", "Layla",
        "Minotaur", "Lolita", "Hayabusa", "Freya", "Gord", "Natalia", "Kagura",
        "Chou", "Sun", "Alpha", "Ruby", "Yi Sun-shin", "Moskov", "Johnson", "Cyclops",
        "Estes", "Hilda", "Aurora", "Lapu-Lapu", "Vexana", "Roger", "Karrie", "Gatotkaca",
        "Harley", "Irithel", "Grock", "Argus", "Odette", "Lancelot", "Diggie", "Hylos",
        "Zhask", "Helcurt", "Pharsa", "Lesley", "Angela", "Gusion", "Valir", "Martis",
        "Uranus", "Hanabi", "Chang'e", "Kaja", "Selena", "Aldous", "Claude", "Vale",
        "Leomord", "Lunox", "Belerick", "Kimmy", "Harith", "Minsitthar", "Kadita",
        "Faramis", "Badang", "Khufra", "Granger", "Guinevere", "Esmeralda", "Terizla",
        "X.Borg", "Ling", "Wan Wan", "Silvanna", "Cecilion", "Carmilla", "Atlas",
        "Popol and Kupa", "Luo Yi", "Yu Zhong", "Mathilda", "Paquito", "Gloo", "Yve",
        "Benedetta", "Brody", "Phoveus", "Natan", "Aulus", "Floryn", "Valentina",
        "Aamon", "Edith", "Yin", "Melissa", "Xavier", "Julian", "Novaria", "Joy"
    ]
    
    RANKS = [
        "Warrior", "Elite", "Master", "Grandmaster", "Epic", 
        "Legend", "Mythic", "Mythical Glory", "Mythical Immortal"
    ]
    
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session: Optional[ClientSession] = None
        logger.info("🤖 MLBB Assistant ініціалізовано")
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = ClientSession(
            timeout=ClientTimeout(total=30, connect=10),
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    def _create_personalized_context(
        self, 
        user_profile: UserProfile, 
        chat_context: ChatContext
    ) -> str:
        """Створює персоналізований контекст для GPT."""
        full_name = f"{user_profile.first_name}"
        if user_profile.last_name:
            full_name += f" {user_profile.last_name}"
        
        username_info = f" (@{user_profile.username})" if user_profile.username else ""
        premium_status = " 👑 Premium" if user_profile.is_premium else ""
        
        context_parts = [
            f"🎮 Ти розмовляєш з {full_name}{username_info}{premium_status}",
            f"📱 Це {chat_context.chat_type} чат MLBB-спільноти",
            f"💬 Користувач написав {user_profile.message_count} повідомлень",
            "🏆 Mobile Legends: Bang Bang - твоя спеціалізація"
        ]
        
        if chat_context.title:
            context_parts.append(f"💭 Назва чату: {chat_context.title}")
        
        if user_profile.mlbb_rank:
            context_parts.append(f"🏅 Ранг користувача: {user_profile.mlbb_rank}")
        
        if user_profile.favorite_heroes:
            heroes_list = ", ".join(user_profile.favorite_heroes[:3])
            context_parts.append(f"❤️ Улюблені герої: {heroes_list}")
        
        return "\n".join(context_parts)
    
    async def get_smart_response(
        self, 
        user_query: str, 
        user_profile: UserProfile, 
        chat_context: ChatContext
    ) -> str:
        """Отримує розумну відповідь від GPT з персоналізацією."""
        if not self.session:
            raise RuntimeError("Session не ініціалізовано")
        
        personalized_context = self._create_personalized_context(user_profile, chat_context)
        
        system_prompt = f"""
{personalized_context}

Ти - експертний асистент Mobile Legends: Bang Bang з дружнім характером.

ТВОЇ ПРИНЦИПИ:
✅ Завжди звертайся до користувача на ім'я
✅ Використовуй емодзі для кращого сприйняття
✅ Давай конкретні та корисні поради по MLBB
✅ Будь ентузіастичним та підтримуючим
✅ Використовуй сучасний український сленг геймерів
✅ Пропонуй стратегії, білди героїв, тактики

ЗАБОРОНЕНО:
❌ HTML теги або markdown
❌ Довгі відповіді (максимум 300 слів)
❌ Загальні фрази без деталей
❌ Інформація не пов'язана з MLBB

Відповідай так, ніби ти досвідчений тіммейт по MLBB!
"""
        
        payload = {
            "model": "gpt-4o-mini",  # Більш економічна модель
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "max_tokens": 400,
            "temperature": 0.8,
            "presence_penalty": 0.3,
            "frequency_penalty": 0.2
        }
        
        try:
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"OpenAI API помилка {response.status}: {error_text}")
                    return f"Вибач, {user_profile.first_name}, сталася технічна проблема 😔"
                
                result = await response.json()
                gpt_response = result["choices"][0]["message"]["content"]
                
                # Очищення від потенційних тегів
                clean_response = re.sub(r"<[^>]*>", "", gpt_response)
                clean_response = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean_response)  # markdown bold
                clean_response = re.sub(r"\*([^*]+)\*", r"\1", clean_response)      # markdown italic
                
                return clean_response.strip()
                
        except Exception as e:
            logger.exception(f"Помилка GPT запиту: {e}")
            return f"Пробач, {user_profile.first_name}, не зміг обробити твій запит 😕"


# --- Bot Initialization ---
bot: Bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp: Dispatcher = Dispatcher()
db: MLBBDatabase = MLBBDatabase()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Розширене привітання з персоналізацією."""
    user_profile = db.get_or_create_user(message.from_user)
    chat_context = db.get_or_create_chat(message.chat)
    
    # Визначаємо час доби для привітання
    current_hour = datetime.now().hour
    if 5 <= current_hour < 12:
        greeting = "Доброго ранку"
    elif 12 <= current_hour < 17:
        greeting = "Доброго дня"
    elif 17 <= current_hour < 22:
        greeting = "Доброго вечора"
    else:
        greeting = "Доброї ночі"
    
    # Персоналізоване привітання
    name = user_profile.first_name
    premium_icon = " 👑" if user_profile.is_premium else ""
    
    welcome_text = f"""
{greeting}, <b>{name}</b>{premium_icon}! 🎮

🔥 Вітаю в MLBB Assistant Bot - твоєму персональному помічнику по Mobile Legends!

<b>🚀 Що я вмію:</b>
• 💬 Відповідаю на запити командою /go
• 🏆 Допомагаю з стратегіями та білдами
• 📊 Аналізую мету та герів
• 🎯 Даю поради по ранкових матчах

<b>🎪 Додаткові команди:</b>
• /heroes - список всіх героїв
• /ranks - система рангів
• /tips - корисні поради
• /stats - твоя статистика

<i>Готовий до перемоги? Використай /go та задай своє питання! 💪</i>
"""
    
    # Створюємо клавіатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏆 Герої", callback_data="show_heroes"),
            InlineKeyboardButton(text="📊 Ранги", callback_data="show_ranks")
        ],
        [
            InlineKeyboardButton(text="💡 Поради", callback_data="show_tips"),
            InlineKeyboardButton(text="📈 Статистика", callback_data="show_stats")
        ]
    ])
    
    try:
        await message.answer(welcome_text, reply_markup=keyboard)
        logger.info(f"✅ Привітання надіслано користувачу {name} (ID: {user_profile.user_id})")
    except TelegramAPIError as e:
        logger.error(f"Помилка відправки привітання: {e}")


@dp.message(Command("go"))
async def cmd_go(message: Message) -> None:
    """Розширена обробка GPT запитів з персоналізацією."""
    user_profile = db.get_or_create_user(message.from_user)
    chat_context = db.get_or_create_chat(message.chat)
    
    user_query = message.text.replace("/go", "", 1).strip()
    
    if not user_query:
        await message.reply(
            f"Привіт, {user_profile.first_name}! 👋\n"
            "Напиши свій запит після команди /go\n\n"
            "<i>Приклад: /go як грати за Ling?</i>"
        )
        return
    
    # Показуємо що бот думає
    thinking_msg = await message.reply(
        f"🤔 {user_profile.first_name}, аналізую твій запит...\n"
        "⚡ GPT готує детальну відповідь!"
    )
    
    start_time = time.time()
    
    async with MLBBAssistant(OPENAI_API_KEY) as assistant:
        response = await assistant.get_smart_response(
            user_query, user_profile, chat_context
        )
    
    processing_time = time.time() - start_time
    
    # Додаємо інфо про час обробки для адміна
    footer = ""
    if message.from_user.id == ADMIN_USER_ID:
        footer = f"\n\n<i>⏱ Обробка: {processing_time:.2f}с</i>"
    
    try:
        await thinking_msg.edit_text(f"{response}{footer}")
        logger.info(f"📤 GPT відповідь надіслана користувачу {user_profile.first_name}")
    except TelegramAPIError as e:
        logger.error(f"Помилка редагування повідомлення: {e}")
        await message.reply(response)


@dp.message(Command("heroes"))
async def cmd_heroes(message: Message) -> None:
    """Показує список героїв MLBB."""
    user_profile = db.get_or_create_user(message.from_user)
    
    heroes_text = f"🏆 <b>Герої Mobile Legends, {user_profile.first_name}!</b>\n\n"
    
    # Групуємо героїв по ролях (приблизно)
    heroes_by_role = {
        "🗡 Assassin": ["Alucard", "Saber", "Natalia", "Hayabusa", "Fanny", "Lancelot", "Gusion", "Selena", "Helcurt", "Leomord", "Ling", "Benedetta", "Aamon", "Yin"],
        "🏹 Marksman": ["Miya", "Bruno", "Clint", "Layla", "Moskov", "Karrie", "Irithel", "Lesley", "Hanabi", "Claude", "Granger", "Wan Wan", "Brody", "Natan", "Melissa"],
        "⚔️ Fighter": ["Tigreal", "Akai", "Freya", "Chou", "Sun", "Alpha", "Ruby", "Lapu-Lapu", "Roger", "Argus", "Martis", "Aldous", "Leomord", "Terizla", "X.Borg", "Silvanna", "Yu Zhong", "Paquito", "Aulus", "Phoveus", "Edith", "Julian"],
        "🛡 Tank": ["Franco", "Minotaur", "Lolita", "Johnson", "Gatotkaca", "Grock", "Hylos", "Uranus", "Belerick", "Khufra", "Atlas", "Baxia"],
        "🔮 Mage": ["Alice", "Nana", "Eudora", "Gord", "Kagura", "Cyclops", "Aurora", "Vexana", "Harley", "Pharsa", "Valir", "Chang'e", "Lunox", "Kimmy", "Harith", "Kadita", "Zhask", "Luo Yi", "Yve", "Valentina", "Xavier", "Novaria"],
        "💚 Support": ["Rafaela", "Estes", "Diggie", "Angela", "Kaja", "Faramis", "Carmilla", "Mathilda", "Floryn", "Joy"]
    }
    
    for role, heroes in heroes_by_role.items():
        heroes_text += f"<b>{role}:</b>\n"
        heroes_text += ", ".join(heroes[:8])  # Показуємо перші 8 героїв кожної ролі
        if len(heroes) > 8:
            heroes_text += f" <i>та ще {len(heroes) - 8}...</i>"
        heroes_text += "\n\n"
    
    heroes_text += "<i>💡 Використай /go [ім'я героя], щоб дізнатися більше!</i>"
    
    await message.answer(heroes_text)


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Показує статистику користувача."""
    user_profile = db.get_or_create_user(message.from_user)
    
    days_since_join = (datetime.now(timezone.utc) - user_profile.join_date).days
    
    stats_text = f"""
📊 <b>Статистика {user_profile.first_name}</b>

👤 <b>Профіль:</b>
• ID: <code>{user_profile.user_id}</code>
• Приєднався: {days_since_join} днів тому
• Повідомлень: {user_profile.message_count}
• Premium: {"✅" if user_profile.is_premium else "❌"}

🎮 <b>MLBB Дані:</b>
• Ранг: {user_profile.mlbb_rank or "Не встановлено"}
• Улюблені герої: {len(user_profile.favorite_heroes)}

💬 <b>Активність:</b>
• Середньо повідомлень/день: {user_profile.message_count / max(days_since_join, 1):.1f}
"""
    
    await message.answer(stats_text)


@dp.message(F.text.contains("ранг") | F.text.contains("rank"))
async def handle_rank_mention(message: Message) -> None:
    """Автоматично реагує на згадки рангу."""
    user_profile = db.get_or_create_user(message.from_user)
    
    # Шукаємо ранг в повідомленні
    text_lower = message.text.lower()
    found_rank = None
    
    for rank in MLBBAssistant.RANKS:
        if rank.lower() in text_lower:
            found_rank = rank
            break
    
    if found_rank and not user_profile.mlbb_rank:
        user_profile.mlbb_rank = found_rank
        await message.reply(
            f"🏅 Круто, {user_profile.first_name}! "
            f"Запам'ятав що ти {found_rank}! 💪"
        )


@dp.errors()
async def global_error_handler(event: Any, exception: Exception) -> Any:
    """Розширений глобальний обробник помилок."""
    error_id = int(time.time())
    logger.error(
        f"🚨 Помилка #{error_id}: {type(exception).__name__}: {exception}",
        exc_info=True
    )
    
    # Сповіщаємо адміна про критичні помилки
    if ADMIN_USER_ID and hasattr(event, 'message'):
        try:
            await bot.send_message(
                ADMIN_USER_ID,
                f"🚨 <b>Помилка в боті #{error_id}</b>\n\n"
                f"<b>Тип:</b> {type(exception).__name__}\n"
                f"<b>Повідомлення:</b> {str(exception)[:500]}\n"
                f"<b>Користувач:</b> {event.message.from_user.first_name if event.message else 'Unknown'}"
            )
        except Exception as notify_error:
            logger.error(f"Не вдалося сповістити адміна: {notify_error}")


async def startup_sequence() -> None:
    """Послідовність запуску бота."""
    logger.info("🚀 Запуск MLBB Bot...")
    
    try:
        # Перевіряємо з'єднання з Telegram
        bot_info = await bot.get_me()
        logger.info(f"✅ Підключено як @{bot_info.username}")
        
        # Сповіщаємо адміна про запуск
        if ADMIN_USER_ID:
            try:
                await bot.send_message(
                    ADMIN_USER_ID,
                    f"🤖 <b>MLBB Bot запущено!</b>\n\n"
                    f"⏰ Час: {datetime.now().strftime('%H:%M:%S')}\n"
                    f"🆔 Бот: @{bot_info.username}\n"
                    f"🟢 Статус: Онлайн"
                )
            except Exception as e:
                logger.warning(f"Не вдалося сповістити адміна про запуск: {e}")
        
        await dp.start_polling(bot, skip_updates=True)
        
    except Exception as exc:
        logger.critical(f"💥 Критична помилка запуску: {exc}", exc_info=True)
        raise


async def shutdown_sequence() -> None:
    """Послідовність зупинки бота."""
    logger.info("🛑 Зупинка MLBB Bot...")
    
    if ADMIN_USER_ID:
        try:
            await bot.send_message(
                ADMIN_USER_ID,
                f"🛑 <b>MLBB Bot зупинено</b>\n\n"
                f"⏰ Час: {datetime.now().strftime('%H:%M:%S')}\n"
                f"🔴 Статус: Офлайн"
            )
        except Exception as e:
            logger.warning(f"Не вдалося сповістити адміна про зупинку: {e}")
    
    await bot.session.close()


async def main() -> None:
    """Основна функція запуску."""
    try:
        await startup_sequence()
    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем (Ctrl+C)")
    except SystemExit:
        logger.info("👋 Бот зупинено системою")
    except Exception as e:
        logger.critical(f"💥 Неочікувана помилка: {e}", exc_info=True)
    finally:
        await shutdown_sequence()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Програма завершена")
    except Exception as e:
        logger.critical(f"💥 Фатальна помилка: {e}", exc_info=True)
