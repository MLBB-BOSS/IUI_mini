import html
import logging
import re

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

# Отримуємо logger з конфігураційного файлу або створюємо новий, якщо потрібно
# Це залежить від того, як ви хочете керувати логуванням у різних модулях.
# Для простоти, припустимо, що logger з config.py доступний або ми ініціалізуємо його тут.
# Якщо config.logger доступний глобально:
# from config import logger, MAX_TELEGRAM_MESSAGE_LENGTH
# Якщо ні, то:
logger = logging.getLogger(__name__)
# Потрібно передати MAX_TELEGRAM_MESSAGE_LENGTH або імпортувати його, якщо він у config.py
# Припустимо, що MAX_TELEGRAM_MESSAGE_LENGTH буде імпортовано з config
# from config import MAX_TELEGRAM_MESSAGE_LENGTH
# Або передано як аргумент, але для простоти імпортуємо:
# Для цього прикладу, я тимчасово задам тут, але краще імпортувати з config.py
MAX_TELEGRAM_MESSAGE_LENGTH = 4090


async def send_message_in_chunks(
    bot_instance: Bot,
    chat_id: int,
    text: str,
    parse_mode: str | None,
    initial_message_to_edit: Message | None = None
):
    """
    Надсилає повідомлення, розбиваючи його на частини, якщо воно занадто довге.
    Редагує initial_message_to_edit першою частиною, якщо надано,
    надсилає наступні частини як нові повідомлення.
    """
    if not text.strip():
        if initial_message_to_edit:
            try:
                await initial_message_to_edit.delete()
                logger.info(f"Видалено thinking_msg для chat_id {chat_id}, оскільки текст порожній.")
            except TelegramAPIError:
                pass # Ігноруємо, якщо не вдалося видалити
        return

    current_pos = 0
    processed_initial_message = False

    if initial_message_to_edit:
        first_chunk_text = text[:MAX_TELEGRAM_MESSAGE_LENGTH]
        if len(text) > MAX_TELEGRAM_MESSAGE_LENGTH:
            split_point = text.rfind('\n', 0, MAX_TELEGRAM_MESSAGE_LENGTH)
            if split_point != -1 and split_point > current_pos:
                first_chunk_text = text[:split_point + 1]

        if first_chunk_text.strip():
            try:
                await initial_message_to_edit.edit_text(first_chunk_text, parse_mode=parse_mode)
                logger.info(f"Відредаговано initial_message_to_edit для chat_id {chat_id}. Довжина частини: {len(first_chunk_text)}")
                current_pos = len(first_chunk_text)
                processed_initial_message = True
            except TelegramAPIError as e:
                logger.warning(f"Не вдалося відредагувати initial_message_to_edit для chat_id {chat_id}: {e}. Повідомлення буде надіслано частинами.")
                try:
                    await initial_message_to_edit.delete()
                except TelegramAPIError:
                    pass
                processed_initial_message = True 
        else:
             try:
                await initial_message_to_edit.delete()
                logger.info(f"Видалено thinking_msg для chat_id {chat_id}, оскільки перша частина порожня.")
             except TelegramAPIError: pass
             processed_initial_message = True


    while current_pos < len(text):
        remaining_text_length = len(text) - current_pos
        chunk_size_to_cut = min(MAX_TELEGRAM_MESSAGE_LENGTH, remaining_text_length)

        actual_chunk_size = chunk_size_to_cut
        if chunk_size_to_cut < remaining_text_length: 
            split_point = text.rfind('\n', current_pos, current_pos + chunk_size_to_cut)
            if split_point != -1 and split_point > current_pos: 
                actual_chunk_size = (split_point - current_pos) + 1
            
        chunk = text[current_pos : current_pos + actual_chunk_size]
        current_pos += actual_chunk_size

        if not chunk.strip():
            continue

        try:
            if not processed_initial_message and initial_message_to_edit is None:
                 await bot_instance.send_message(chat_id, chunk, parse_mode=parse_mode)
                 processed_initial_message = True 
            else:
                 await bot_instance.send_message(chat_id, chunk, parse_mode=parse_mode)

            logger.info(f"Надіслано частину повідомлення для chat_id {chat_id}. Довжина: {len(chunk)}")
        except TelegramAPIError as e:
            logger.error(f"Telegram API помилка при надсиланні частини для chat_id {chat_id}: {e}. Частина (100): {html.escape(chunk[:100])}")
            if "can't parse entities" in str(e).lower() or "unclosed" in str(e).lower() or "expected" in str(e).lower():
                plain_chunk = re.sub(r"<[^>]+>", "", chunk) 
                if plain_chunk.strip():
                    try:
                        await bot_instance.send_message(chat_id, plain_chunk, parse_mode=None)
                        logger.info(f"Надіслано частину повідомлення як простий текст для chat_id {chat_id}. Довжина: {len(plain_chunk)}")
                        continue
                    except TelegramAPIError as plain_e:
                        logger.error(f"Не вдалося надіслати частину як простий текст для chat_id {chat_id}: {plain_e}")
            break
