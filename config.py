# config.py
import logging
import os
from dotenv import load_dotenv

# === НАЛАШТУВАННЯ ЛОГУВАННЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# === ЗАВАНТАЖЕННЯ ЗМІННИХ СЕРЕДОВИЩА ===
# load_dotenv() потрібно для локального запуску та тестування.
# На Heroku Config Vars завантажуються автоматично.
load_dotenv()

# === ЗАВАНТАЖЕННЯ КЛЮЧІВ ТА URL ===
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("API_Gemini", "")
GOOGLE_CLOUD_PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT_ID", "")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

# Розділено URL для синхронних та асинхронних операцій
SYNC_DATABASE_URL: str = os.getenv("DATABASE_URL", "")
ASYNC_DATABASE_URL: str = os.getenv("AS_BASE", "") # Використовуємо AS_BASE для async

# === КОНСТАНТИ ===
WELCOME_IMAGE_URL: str = "https://res.cloudinary.com/ha1pzppgf/image/upload/v1748286434/file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"
MAX_TELEGRAM_MESSAGE_LENGTH: int = 4090
MAX_CHAT_HISTORY_LENGTH: int = 10

# === КОНФІГУРАЦІЯ ДЛЯ АДАПТИВНОЇ ПРИСУТНОСТІ ===
BOT_NAMES: list[str] = [
    "бот", "genius", "iui", # Основні
    "gg", "гг",             # Ігрові звернення
    "ai", "аі", "іі"        # Технічні та фонетичні звернення
]
CONVERSATIONAL_COOLDOWN_SECONDS: int = 600 # 10 хвилин

# === НОВА КОНФІГУРАЦІЯ ДЛЯ ПАТІ-МЕНЕДЖЕРА ===
PARTY_TRIGGER_PHRASES: list[str] = [
    "хто в паті", "го паті", "збираю паті", "шукаю паті", "погнали паті",
    "хто грати", "го грати", "погнали грати", "хто катку",
    "паті", "збір", "тіма", "тіму", "катку",
    "+ в паті", "хто +", "плюс в паті",
    "є хто грати", "погнали в паті", "збір на рейтинг", "го на рейт",
    "шукаю тімейтів", "го катку разом"
]
PARTY_LOBBY_ROLES: list[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]
PARTY_LOBBY_COOLDOWN_SECONDS: int = 60 # 1 хвилина на створення нового лобі в чаті

# === КОНФІГУРАЦІЯ ТРИГЕРІВ ДЛЯ РОЗМОВИ ===
CONVERSATIONAL_TRIGGERS: dict[str, str] = {
    "як справи": "Дружньо і коротко поцікався, як справи у співрозмовника.",
    "що робиш": "Відповідай коротко і з гумором, ніби тебе відволікли від аналізу реплеїв.",
    "привіт": "Привітайся у відповідь, використовуй молодіжний сленг.",
    "дякую": "Відповідай люб'язно, що завжди радий допомогти, адже ти GGenius.",
    "що ти вмієш": "Розкажи коротко про свої основні функції: аналіз скріншотів, поради по грі та допомога у зборі паті.",
    "хто тебе створив": "Відповідай з повагою та гумором, що ти — результат праці та генія MLBB-BOSS, створений для спільноти.",
    "ти бот": "Підтверди, що ти AI, але з характером справжнього геймера."
}

# === КОНФІГУРАЦІЯ УНІВЕРСАЛЬНОГО VISION МОДУЛЯ ===
VISION_AUTO_RESPONSE_ENABLED: bool = True
VISION_RESPONSE_COOLDOWN_SECONDS: int = 30
VISION_MAX_IMAGE_SIZE_MB: float = 10.0
VISION_QUALITY_THRESHOLD: str = "low"

VISION_SUPPORTED_TYPES: list[str] = [
    "meme", "screenshot", "text", "profile", "stats", "gameplay", "hero",
    "items", "patch_notes", "tournament", "general"
]

VISION_CONTENT_EMOJIS: dict[str, str] = {
    "meme": "😂", "screenshot": "📸", "text": "📝", "profile": "👤",
    "stats": "📊", "gameplay": "🎮", "hero": "🦸", "items": "⚔️",
    "patch_notes": "📋", "tournament": "🏆", "general": "🔍"
}

# === КОНФІГУРАЦІЯ REPLY KEYBOARD НАВІГАЦІЇ ===
REPLY_KEYBOARD_ENABLED: bool = True
SHOW_COMMANDS_HELP: bool = False

BOT_MODES: dict[str, str] = {
    "main": "Головне меню", "go": "AI-асистент режим",
    "analysis": "Режим аналізу", "party": "Режим збору паті"
}

NAVIGATION_TEXTS: dict[str, str] = {
    "welcome": "🎮 Ласкаво просимо до GGenius!\n\nОберіть потрібну дію з меню нижче:",
    "go_mode": "🤖 Режим AI-асистента активовано!\n\nЗадавайте будь-які питання про MLBB, і я дам детальну відповідь:",
    "profile_mode": "🧑‍💼 Режим аналізу профілю!\n\nНадішліть скріншот вашого профілю в MLBB для детального аналізу:",
    "stats_mode": "📊 Режим аналізу статистики!\n\nНадішліть скріншот вашої статистики в MLBB:",
    "party_mode": "🎮 Режим збору паті активовано!\n\nНапишіть про пошук команди, і я допоможу організувати лобі:",
    "back_to_main": "🏠 Повертаємося до головного меню.",
    "help_text": "❓ Допомога:\n\n🧑‍💼 **Профіль** - аналіз скріншота профілю\n📊 **Статистика** - аналіз статистики аккаунту\n🤖 **GO** - універсальний AI-асистент\n🎮 **Зібрати паті** - допомога в пошуку команди"
}

# === ПЕРЕВІРКА КРИТИЧНИХ ЗМІННИХ ===
# Оновлено перевірку, тепер включає обидва URL бази даних
if not all([TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, GEMINI_API_KEY, GOOGLE_CLOUD_PROJECT_ID, SYNC_DATABASE_URL, ASYNC_DATABASE_URL]):
    critical_vars = {
        "TELEGRAM_BOT_TOKEN": bool(TELEGRAM_BOT_TOKEN),
        "OPENAI_API_KEY": bool(OPENAI_API_KEY),
        "API_Gemini": bool(GEMINI_API_KEY),
        "GOOGLE_CLOUD_PROJECT_ID": bool(GOOGLE_CLOUD_PROJECT_ID),
        "DATABASE_URL (sync)": bool(SYNC_DATABASE_URL),
        "AS_BASE (async)": bool(ASYNC_DATABASE_URL)
    }
    missing_vars = [key for key, value in critical_vars.items() if not value]
    error_message = f"❌ Не встановлено критично важливі змінні в Heroku Config Vars: {', '.join(missing_vars)}"
    logger.critical(error_message)
    raise RuntimeError(error_message)

# Додано логування для перевірки, що змінні завантажені
logger.info(f"Модель для Vision (аналіз скріншотів): gpt-4o-mini (жорстко задано)")
logger.info(f"Модель для текстових генерацій (/go, опис профілю): gpt-4.1-turbo (жорстко задано)")
logger.info(f"Модель для пошуку в Інтернеті (/search): Gemini 2.5 Pro (жорстко задано)")
logger.info(f"Універсальний Vision модуль: {'УВІМКНЕНО' if VISION_AUTO_RESPONSE_ENABLED else 'ВИМКНЕНО'}")
logger.info(f"Reply Keyboard навігація: {'УВІМКНЕНО' if REPLY_KEYBOARD_ENABLED else 'ВИМКНЕНО'}")
logger.info(f"✅ Google Cloud Project ID: '{GOOGLE_CLOUD_PROJECT_ID}' завантажено.")
logger.info(f"✅ Gemini API Key завантажено (перевірте Heroku Config Vars).")
logger.info(f"✅ SYNC_DATABASE_URL завантажено (перевірте Heroku Config Vars).")
logger.info(f"✅ ASYNC_DATABASE_URL (з AS_BASE) завантажено (перевірте Heroku Config Vars).")
