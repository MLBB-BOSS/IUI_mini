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
BOT_NAMES: list[str] = ["бот", "genius", "iui"]
CONVERSATIONAL_COOLDOWN_SECONDS: int = 600 # 10 хвилин

# === НОВА КОНФІГУРАЦІЯ ДЛЯ ПАТІ-МЕНЕДЖЕРА ===
PARTY_TRIGGER_PHRASES: list[str] = [
    "хто в паті", "го паті", "збираю паті", "шукаю паті", "погнали паті",
    "хто грати", "го грати", "погнали грати", "хто катку"
]
PARTY_LOBBY_ROLES: list[str] = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]
PARTY_LOBBY_COOLDOWN_SECONDS: int = 60 # 1 хвилина на створення нового лобі в чаті

# === КОНФІГУРАЦІЯ ТРИГЕРІВ ДЛЯ РОЗМОВИ ===
CONVERSATIONAL_TRIGGERS: dict[str, str] = {
    "як справи": "Дружньо і коротко поцікався, як справи у співрозмовника.",
    "що робиш": "Відповідай коротко і з гумором, ніби тебе відволікли від чогось важливого.",
    "привіт": "Привітайся у відповідь, використовуй молодіжний сленг.",
    "дякую": "Відповідай люб'язно, що завжди радий допомогти.",
}

# === ПЕРЕВІРКА КРИТИЧНИХ ЗМІННИХ ===
if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logger.critical("❌ TELEGRAM_BOT_TOKEN та OPENAI_API_KEY повинні бути встановлені в .env файлі")
    raise RuntimeError("❌ Встанови TELEGRAM_BOT_TOKEN та OPENAI_API_KEY в .env файлі")

logger.info(f"Модель для Vision (аналіз скріншотів): gpt-4o-mini (жорстко задано)")
logger.info(f"Модель для текстових генерацій (/go, опис профілю): gpt-4.1-turbo (жорстко задано)")
