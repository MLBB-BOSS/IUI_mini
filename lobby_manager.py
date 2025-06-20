import time
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import database
from config import logger
from handlers.general_handlers import format_lobby_message, update_lobby_message

async def check_expired_lobbies(bot: Bot):
    """
    Перевіряє всі активні лобі в базі даних.
    Якщо час життя лобі вичерпано, розформовує його.
    """
    try:
        all_lobbies = database.get_all_lobbies()
        current_time = int(time.time())

        for lobby in all_lobbies:
            if current_time > lobby["expires_at"]:
                logger.info(f"Лобі в чаті {lobby['chat_id']} вичерпало час. Розформовую...")
                try:
                    await bot.edit_message_text(
                        text="⌛️ <b>Час очікування вичерпано. Лобі розформовано.</b>",
                        chat_id=lobby["chat_id"],
                        message_id=lobby["message_id"],
                        reply_markup=None # Видаляємо кнопки
                    )
                except TelegramAPIError as e:
                    logger.warning(f"Не вдалося оновити повідомлення для простроченого лобі в чаті {lobby['chat_id']}: {e}")
                finally:
                    # Видаляємо лобі з бази даних незалежно від успіху редагування повідомлення
                    database.remove_lobby(lobby["chat_id"])

    except Exception as e:
        logger.error(f"Критична помилка у фоновому завданні check_expired_lobbies: {e}", exc_info=True)
