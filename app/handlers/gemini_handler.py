import io
import logging
from typing import List, Dict, Any

from aiogram import Router, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.chat_action import ChatActionSender

from app.services.gemini_service import fetch_gemini_response

# Створюємо роутер та сховище для FSM.
# MemoryStorage - простий варіант, для production варто розглянути Redis.
gemini_router = Router()
storage = MemoryStorage()

# Ключ для зберігання історії в FSMContext. Тепер він знаходиться тут.
HISTORY_KEY = "gemini_history"

# Розширюємо список тригерів для більшої гнучкості
TRIGGER_WORDS = ["gemini", "геміні", "проаналізуй", "допоможи", "поясни", "розкажи"]

async def get_history(state: FSMContext) -> List[Dict[str, Any]]:
    """Безпечно отримує історію з FSM, повертаючи порожній список, якщо її немає."""
    user_data = await state.get_data()
    return user_data.get(HISTORY_KEY, [])

# --- Обробники команд ---

@gemini_router.message(Command("start", "help"))
async def start_handler(message: types.Message):
    """Обробник команд /start та /help."""
    await message.answer(
        "Привіт! Я ваш персональний MLBB-асистент на базі Gemini.\n\n"
        "Як я можу допомогти:\n"
        "- **Аналіз скріншотів:** Надішліть скріншот матчу, і я проаналізую його.\n"
        "- **Відповіді на питання:** Задайте питання, почавши його зі слова-тригера (напр. `геміні, яка зараз мета?`).\n"
        "- **Пряма команда:** Використовуйте `/gemini <ваш запит>`.\n\n"
        "Щоб почати нову розмову (очистити пам'ять), введіть /newchat."
    )

@gemini_router.message(Command("newchat"))
async def new_chat_handler(message: types.Message, state: FSMContext):
    """Очищує історію розмови для користувача."""
    await state.clear()
    await message.answer("Історію розмови очищено. Починаємо з чистого аркуша!")

@gemini_router.message(Command("gemini"))
async def gemini_command_handler(message: types.Message, command: CommandObject, state: FSMContext):
    """Обробник команди /gemini."""
    query = command.args
    if not query:
        await message.reply(
            "Будь ласка, введіть ваш запит після команди. Наприклад: `/gemini проаналізуй мій останній матч`"
        )
        return
    await process_gemini_request(message, query, state)

# --- Обробники контенту ---

@gemini_router.message(F.photo)
async def gemini_photo_handler(message: types.Message, state: FSMContext):
    """
    Обробляє повідомлення з фото. Використовує підпис до фото як запит.
    """
    # Запит - це текст підпису до фото, або стандартна фраза, якщо підпису немає.
    query = message.caption if message.caption else "Детально проаналізуй це зображення"
    
    # Завантажуємо фото в найкращій якості
    photo_buffer = io.BytesIO()
    await message.bot.download(message.photo[-1], destination=photo_buffer)
    
    await process_gemini_request(message, query, state, image_data=photo_buffer.getvalue())

@gemini_router.message(F.text)
async def gemini_text_handler(message: types.Message, state: FSMContext):
    """
    Обробляє текстові повідомлення, якщо вони містять тригерні слова.
    """
    text = message.text.lower()
    if any(word in text for word in TRIGGER_WORDS):
        await process_gemini_request(message, message.text, state)
    # Якщо тригерів немає, бот не відповідатиме, що є правильною поведінкою.

# --- Центральна функція обробки ---

async def process_gemini_request(
    message: types.Message,
    query: str,
    state: FSMContext,
    image_data: bytes | None = None
):
    """
    Центральна функція для обробки запитів до Gemini.
    Вона керує історією, показує статус "друкує..." та надсилає відповідь.
    """
    try:
        # Показуємо "друкує..." для кращого UX
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            history = await get_history(state)
            
            # Викликаємо оновлений сервіс
            response_text, updated_history = await fetch_gemini_response(
                history=history,
                query=query,
                image_data=image_data
            )
            
            # Зберігаємо оновлену історію в FSM
            await state.update_data({HISTORY_KEY: updated_history})
            
            # Відповідаємо користувачу
            await message.reply(response_text, parse_mode="Markdown")
            
    except Exception as e:
        logging.error(f"Error in process_gemini_request: {e}", exc_info=True)
        await message.reply("На жаль, сталася внутрішня помилка. Спробуйте повторити запит пізніше.")
