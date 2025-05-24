import os
import logging

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не встановлено! Бот не зможе запуститися.")
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required in environment variables.")

__all__ = ["TELEGRAM_BOT_TOKEN"]
