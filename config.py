# config.py
"""
Configuration settings and environment variables for the MLBB IUI Mini bot.

This module loads critical tokens and URLs from environment variables,
sets up logging, and validates that all required settings are present.
"""
import logging
import os

from dotenv import load_dotenv

# ------------------------------------------------------------------------------
# Logging configuration
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Load environment variables (for local development via .env)
# ------------------------------------------------------------------------------
# On Heroku, Config Vars are provided via the environment automatically.
load_dotenv()

# ------------------------------------------------------------------------------
# Required credentials and URLs
# ------------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GOOGLE_CLOUD_PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT_ID", "")
CLOUDINARY_URL: str = os.getenv("CLOUDINARY_URL", "")

# ------------------------------------------------------------------------------
# Redis configuration
# ------------------------------------------------------------------------------
# Heroku RedisCloud provides REDISCLOUD_URL; fallback to REDIS_URL if set.
REDISCLOUD_URL: str = os.getenv("REDISCLOUD_URL", "")
REDIS_URL: str = os.getenv("REDIS_URL") or REDISCLOUD_URL

# ------------------------------------------------------------------------------
# Database URLs (sync and async)
# ------------------------------------------------------------------------------
SYNC_DATABASE_URL: str = os.getenv("DATABASE_URL", "")
ASYNC_DATABASE_URL: str = os.getenv("AS_BASE", "")  # Use AS_BASE for async URL

# ------------------------------------------------------------------------------
# Other core settings
# ------------------------------------------------------------------------------
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

WELCOME_IMAGE_URL: str = (
    "https://res.cloudinary.com/ha1pzppgf/"
    "image/upload/v1748286434/"
    "file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"
)
MAX_TELEGRAM_MESSAGE_LENGTH: int = 4090
MAX_CHAT_HISTORY_LENGTH: int = 10

# ------------------------------------------------------------------------------
# Conversation & Vision settings
# ------------------------------------------------------------------------------
BOT_NAMES: list[str] = [
    "бот", "genius", "iui",  # Основні
    "gg", "гг",              # Ігрові звернення
    "ai", "аі", "іі"         # Технічні та фонетичні
]
CONVERSATIONAL_COOLDOWN_SECONDS: int = 600  # 10 minutes
SEARCH_COOLDOWN_SECONDS: int = 300 # 5 minutes
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

# ------------------------------------------------------------------------------
# Party manager configuration
# ------------------------------------------------------------------------------
PARTY_TRIGGER_PHRASES: list[str] = [
    "хто в паті", "го паті", "збираю паті", "шукаю паті", "погнали паті",
    "хто грати", "го грати", "погнали грати", "хто катку",
    "паті", "збір", "тіма", "тіму", "катку",
    "+ в паті", "хто +", "плюс в паті",
    "є хто грати", "погнали в паті", "збір на рейтинг", "го на рейт",
    "шукаю тімейтів", "го катку разом"
]
PARTY_LOBBY_ROLES: list[str] = [
    "Танк/Підтримка", "Лісник", "Маг (мід)",
    "Стрілець (золото)", "Боєць (досвід)"
]
PARTY_LOBBY_COOLDOWN_SECONDS: int = 60  # 1 minute per lobby creation

# ------------------------------------------------------------------------------
# Reply keyboard navigation settings
# ------------------------------------------------------------------------------
REPLY_KEYBOARD_ENABLED: bool = True
SHOW_COMMANDS_HELP: bool = False

BOT_MODES: dict[str, str] = {
    "main": "Головне меню",
    "go": "AI-асистент режим",
    "analysis": "Режим аналізу",
    "party": "Режим збору паті"
}
NAVIGATION_TEXTS: dict[str, str] = {
    "welcome": "🎮 Ласкаво просимо до GGenius!\n\nОберіть потрібну дію з меню нижче:",
    "go_mode": "🤖 Режим AI-асистента активовано!\n\nЗадавайте будь-які питання про MLBB, і я дам детальну відповідь:",
    "profile_mode": "🧑‍💼 Режим аналізу профілю!\n\nНадішліть скріншот вашого профілю в MLBB для детального аналізу:",
    "stats_mode": "📊 Режим аналізу статистики!\n\nНадішліть скріншот вашої статистики в MLBB:",
    "party_mode": "🎮 Режим збору паті активовано!\n\nНапишіть про пошук команди, і я допоможу організувати лобі:",
    "back_to_main": "🏠 Повертаємося до головного меню.",
    "help_text": (
        "❓ Допомога:\n\n"
        "🧑‍💼 **Профіль** - аналіз скріншота профілю\n"
        "📊 **Статистика** - аналіз статистики аккаунту\n"
        "🤖 **GO** - універсальний AI-асистент\n"
        "🎮 **Зібрати паті** - допомога в пошуку команди"
    )
}

# ------------------------------------------------------------------------------
# Conversational triggers for chat responses
# ------------------------------------------------------------------------------
CONVERSATIONAL_TRIGGERS: dict[str, str] = {
    # Базові соціальні тригери
    "як справи": "Дружньо і коротко поцікався, як справи у співрозмовника.",
    "що робиш": "Відповідай коротко і з гумором, ніби тебе відволікли від аналізу реплеїв.",
    "привіт": "Привітайся у відповідь, використовуй молодіжний сленг.",
    "дякую": "Відповідай люб'язно, що завжди радий допомогти, адже ти GGenius.",
    "що ти вмієш": (
        "Розкажи коротко про свої основні функції: аналіз скріншотів, "
        "поради по грі та допомога у зборі паті."
    ),
    "хто тебе створив": (
        "Відповідай з повагою та гумором, що ти — результат праці та генія MLBB-BOSS, "
        "створений для спільноти."
    ),
    "ти бот": "Підтверди, що ти AI, але з характером справжнього геймера.",

    # Ігрові емоції та сленг
    "gg": "Відреагуй на 'good game' як справжній геймер, коротко та по-братськи.",
    "ez": "Жартівливо відреагуй на хвастощі про легку перемогу.",
    "лагає": "Співчувай проблемам з пінгом, запропонуй перевірити інтернет.",
    "капець": "Відреагуй з розумінням на фрустрацію гравця.",
    "крутяк": "Підтримай позитивні емоції, похвали.",
    
    # Запити на ігрову пораду
    "який герой": "Коротко порадь героя залежно від контексту (якщо є).",
    "що збирати": "Дай швидку пораду по предметах.",
    "контрпік": "Запропонуй контрпік або скажи, що треба більше контексту.",
    "допоможи": "Запитай, з чим конкретно потрібна допомога."
}

# ------------------------------------------------------------------------------
# Critical environment variable check
# ------------------------------------------------------------------------------
_critical_vars = {
    "TELEGRAM_BOT_TOKEN": bool(TELEGRAM_BOT_TOKEN),
    "OPENAI_API_KEY": bool(OPENAI_API_KEY),
    "GOOGLE_CLOUD_PROJECT_ID": bool(GOOGLE_CLOUD_PROJECT_ID),
    "CLOUDINARY_URL": bool(CLOUDINARY_URL),
    "DATABASE_URL (sync)": bool(SYNC_DATABASE_URL),
    "AS_BASE (async)": bool(ASYNC_DATABASE_URL),
    "REDIS_URL": bool(REDIS_URL),
}
_missing = [name for name, ok in _critical_vars.items() if not ok]
if _missing:
    _msg = (
        f"❌ Missing critical Config Vars: {', '.join(_missing)}. "
        "Please set them in environment or .env"
    )
    logger.critical(_msg)
    raise RuntimeError(_msg)

# ------------------------------------------------------------------------------
# Log loaded configurations for verification
# ------------------------------------------------------------------------------
logger.info("✅ TELEGRAM_BOT_TOKEN loaded.")
logger.info("✅ OPENAI_API_KEY loaded.")
logger.info("✅ GOOGLE_CLOUD_PROJECT_ID loaded.")
logger.info("✅ CLOUDINARY_URL loaded.")
logger.info("✅ SYNC_DATABASE_URL loaded.")
logger.info("✅ ASYNC_DATABASE_URL loaded.")
logger.info("✅ REDIS_URL loaded.")