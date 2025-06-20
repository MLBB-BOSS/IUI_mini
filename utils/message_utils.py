"""
Допоміжні утиліти для роботи з повідомленнями в Telegram.
"""
import asyncio
from typing import Any

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from config import logger

# Максимальна довжина повідомлення, встановлена Telegram API.
# ВИРІШЕННЯ ПРОБЛЕМИ: Ім'я константи уніфіковано для сумісності з іншими модулями (vision_handlers).
MAX_TELEGRAM_MESSAGE_LENGTH = 4096

async def send_message_in_chunks(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: str | None = ParseMode.HTML,
    initial_message_to_edit: Any | None = None,
    **kwargs: Any
) -> None:
    """
    Надсилає довгий текст, розбиваючи його на частини, що не перевищують ліміт Telegram.

    Ця функція є універсальною:
    - Якщо передано `initial_message_to_edit`, вона спочатку редагує це повідомлення
      першою частиною тексту, а решту надсилає новими повідомленнями.
    - Якщо текст короткий, вона просто надсилає або редагує одне повідомлення.
    - Підтримує передачу будь-яких додаткових параметрів (напр., `reply_to_message_id`)
      завдяки `**kwargs`.

    Args:
        bot: Екземпляр `Bot`.
        chat_id: ID чату для відправки.
        text: Повний текст для надсилання.
        parse_mode: Режим парсингу (HTML, MarkdownV2).
        initial_message_to_edit: (Опціонально) Повідомлення для редагування першою частиною.
        **kwargs: Додаткові аргументи для передачі в `bot.send_message` або `bot.edit_message_text`.
    """
    if not text:
        logger.warning("Спроба надіслати порожнє повідомлення в send_message_in_chunks.")
        return

    # Розбиваємо текст на частини, враховуючи межі речень для кращої читабельності
    chunks = []
    while len(text) > 0:
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            chunks.append(text)
            break
        
        chunk = text[:MAX_TELEGRAM_MESSAGE_LENGTH]
        last_newline = chunk.rfind('\n')
        last_space = chunk.rfind(' ')

        split_pos = last_newline if last_newline > 0 else last_space
        if split_pos == -1 or split_pos < MAX_TELEGRAM_MESSAGE_LENGTH / 2:
            split_pos = MAX_TELEGRAM_MESSAGE_LENGTH
        
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    try:
        first_chunk = chunks.pop(0)
        if initial_message_to_edit:
            await bot.edit_message_text(
                text=first_chunk,
                chat_id=chat_id,
                message_id=initial_message_to_edit.message_id,
                parse_mode=parse_mode,
                **kwargs
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=first_chunk,
                parse_mode=parse_mode,
                **kwargs
            )
        logger.info(f"Надіслано/відредаговано першу частину повідомлення для chat_id {chat_id}. Довжина: {len(first_chunk)}")

        for chunk in chunks:
            await asyncio.sleep(0.5)
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode, **kwargs)
            logger.info(f"Надіслано наступну частину повідомлення для chat_id {chat_id}. Довжина: {len(chunk)}")

    except TelegramAPIError as e:
        logger.error(f"Не вдалося надіслати повідомлення в чат {chat_id}: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id,
                "😔 Вибачте, сталася помилка під час відправки відповіді."
            )
        except TelegramAPIError:
            logger.critical(f"Не вдалося надіслати навіть повідомлення про помилку в чат {chat_id}.")
