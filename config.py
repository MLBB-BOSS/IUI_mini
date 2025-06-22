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
load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))

# === КОНСТАНТИ ===
WELCOME_IMAGE_URL: str = "https://res.cloudinary.com/ha1pzppgf/image/upload/v1748286434/file_0000000017a46246b78bf97e2ecd9348_zuk16r.png"
MAX_TELEGRAM_MESSAGE_LENGTH: int = 4090
MAX_CHAT_HISTORY_LENGTH: int = 10

# === КОНФІГУРАЦІЯ ДЛЯ АДАПТИВНОЇ ПРИСУТНОСТІ ===
# Розширений список імен та звернень до бота для максимальної реакції.
BOT_NAMES: list[str] = [
    "бот", "genius", "iui", # Основні
    "gg", "гг",             # Ігрові звернення
    "ai", "аі", "іі"        # Технічні та фонетичні звернення
]
CONVERSATIONAL_COOLDOWN_SECONDS: int = 600 # 10 хвилин

# === НОВА КОНФІГУРАЦІЯ ДЛЯ ПАТІ-МЕНЕДЖЕРА ===
# Розширений список тригерів для запуску FSM створення паті.
PARTY_TRIGGER_PHRASES: list[str] = [
    # Класичні фрази
    "хто в паті", "го паті", "збираю паті", "шукаю паті", "погнали паті",
    "хто грати", "го грати", "погнали грати", "хто катку",
    # Сучасний сленг та скорочення
    "паті", "збір", "тіма", "тіму", "катку",
    # Фрази з символами
    "+ в паті", "хто +", "плюс в паті",
    # Розмовні варіації
    "є хто грати", "погнали в паті", "збір на рейтинг", "го на рейт",
    "шукаю тімейтів", "го катку разом"
]
PARTY_LOBBY_ROLES: list[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]
PARTY_LOBBY_COOLDOWN_SECONDS: int = 60 # 1 хвилина на створення нового лобі в чаті

# === КОНФІГУРАЦІЯ ТРИГЕРІВ ДЛЯ РОЗМОВИ ===
# Розширений список для більш живого спілкування.
CONVERSATIONAL_TRIGGERS: dict[str, str] = {
    # Соціальні
    "як справи": "Дружньо і коротко поцікався, як справи у співрозмовника.",
    "що робиш": "Відповідай коротко і з гумором, ніби тебе відволікли від аналізу реплеїв.",
    "привіт": "Привітайся у відповідь, використовуй молодіжний сленг.",
    "дякую": "Відповідай люб'язно, що завжди радий допомогти, адже ти GGenius.",
    # Про самого бота
    "що ти вмієш": "Розкажи коротко про свої основні функції: аналіз скріншотів, поради по грі та допомога у зборі паті.",
    "хто тебе створив": "Відповідай з повагою та гумором, що ти — результат праці та генія MLBB-BOSS, створений для спільноти.",
    "ти бот": "Підтверди, що ти AI, але з характером справжнього геймера."
}

# === 🆕 КОНФІГУРАЦІЯ УНІВЕРСАЛЬНОГО VISION МОДУЛЯ ===
# Налаштування для автоматичного розпізнавання та обробки зображень
VISION_AUTO_RESPONSE_ENABLED: bool = True  # Включити/вимкнути автореакцію на зображення
VISION_RESPONSE_COOLDOWN_SECONDS: int = 30  # Кулдаун між обробками зображень в одному чаті
VISION_MAX_IMAGE_SIZE_MB: float = 10.0  # Максимальний розмір зображення для обробки (МБ)
VISION_QUALITY_THRESHOLD: str = "low"  # low/auto/high - якість обробки для оптимізації швидкості

# Типи зображень, які бот може розпізнавати та обробляти
VISION_SUPPORTED_TYPES: list[str] = [
    "meme",           # Меми
    "screenshot",     # Скріншоти гри
    "text",           # Зображення з текстом
    "profile",        # Профільні дані гравців
    "stats",          # Статистика гравців
    "gameplay",       # Ігровий процес
    "hero",           # Герої MLBB
    "items",          # Предмети в грі
    "patch_notes",    # Оновлення гри
    "tournament",     # Турнірні матеріали
    "general"         # Загальні зображення
]

# Емодзі для різних типів контенту
VISION_CONTENT_EMOJIS: dict[str, str] = {
    "meme": "😂",
    "screenshot": "📸", 
    "text": "📝",
    "profile": "👤",
    "stats": "📊",
    "gameplay": "🎮",
    "hero": "🦸",
    "items": "⚔️",
    "patch_notes": "📋",
    "tournament": "🏆",
    "general": "🔍"
}

# === ПЕРЕВІРКА КРИТИЧНИХ ЗМІННИХ ===
if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

logger.info(f"Модель для Vision (аналіз скріншотів): gpt-4o-mini (жорстко задано)")
logger.info(f"Модель для текстових генерацій (/go, опис профілю): gpt-4.1-turbo (жорстко задано)")
logger.info(f"🆕 Універсальний Vision модуль: {'УВІМКНЕНО' if VISION_AUTO_RESPONSE_ENABLED else 'ВИМКНЕНО'}")
