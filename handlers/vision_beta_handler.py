"""
Handler for GPT Vision Beta functionality.
Allows users to send an image for general analysis by OpenAI's GPT Vision model.
"""
import base64
import logging
from io import BytesIO
from typing import Union

import aiohttp
import tenacity
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.enums import ParseMode

# Припускаємо, що OPENAI_API_KEY та VISION_MODEL_NAME імпортуються з конфігурації
# Наприклад: from config.settings import OPENAI_API_KEY, VISION_BETA_MODEL_NAME
# Заміни на свої реальні шляхи імпорту та назви змінних
try:
    from config.settings import OPENAI_API_KEY, VISION_BETA_MODEL_NAME
except ImportError:
    logging.critical("OPENAI_API_KEY or VISION_BETA_MODEL_NAME not found in config.settings.")
    # У реальному проекті тут може бути більш витончена обробка або заглушки для розробки
    OPENAI_API_KEY = "YOUR_OPENAI_API_KEY_HERE" # Заглушка
    VISION_BETA_MODEL_NAME = "gpt-4o" # Або "gpt-4-vision-preview"

# Імпортуй свої стани
# Наприклад: from states.all_states import VisionBetaStates
# Або:
from states.vision_states import VisionBetaStates


router = Router(name="vision_beta_handler")
logger = logging.getLogger(__name__)

# Константи
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
MAX_API_RETRIES = 3
API_TIMEOUT_SECONDS = 120 # Збільшено для потенційно довгих відповідей Vision
GENERAL_VISION_PROMPT = (
    "Ти — багатоцільовий аналітичний AI. Опиши це зображення докладно, але лаконічно. "
    "Якщо це скріншот з гри, спробуй визначити гру та ключові елементи на екрані. "
    "Відповідай українською мовою."
)
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024  # 4MB - рекомендований ліміт для GPT-4 Vision


async def download_image(message: Message, bot: Bot) -> Union[BytesIO, None]:
    """
    Downloads the image sent by the user (photo or document).

    Args:
        message: The user's message object.
        bot: The Bot instance.

    Returns:
        A BytesIO object containing the image data, or None if download fails
        or image is too large.
    """
    file_id = None
    file_size = None

    if message.photo:
        # Беремо фото найбільшого розміру
        file_id = message.photo[-1].file_id
        file_size = message.photo[-1].file_size
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id
        file_size = message.document.file_size
    else:
        await message.reply(
            "Будь ласка, надішліть зображення як фото або як документ (файл)."
        )
        return None

    if file_id and file_size:
        if file_size > MAX_IMAGE_SIZE_BYTES:
            await message.reply(
                f"Вибачте, зображення занадто велике ({(file_size / (1024*1024)):.1f}MB). "
                f"Максимально допустимий розмір: {(MAX_IMAGE_SIZE_BYTES / (1024*1024)):.0f}MB."
            )
            return None
        try:
            file_info = await bot.get_file(file_id)
            if not file_info.file_path:
                logger.error(f"Failed to get file_path for file_id: {file_id}")
                return None
            image_bytes_io = await bot.download_file(file_info.file_path)
            return image_bytes_io
        except TelegramAPIError as e:
            logger.error(f"Telegram API error downloading image {file_id}: {e}")
            await message.reply("Не вдалося завантажити зображення. Спробуйте ще раз.")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error downloading image {file_id}: {e}")
            await message.reply("Сталася несподівана помилка при завантаженні зображення.")
            return None
    return None


@tenacity.retry(
    stop=tenacity.stop_after_attempt(MAX_API_RETRIES),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    retry=tenacity.retry_if_exception_type(aiohttp.ClientError),
    reraise=True,
)
async def call_openai_vision_api(
    base64_image: str,
    prompt: str,
    model: str = VISION_BETA_MODEL_NAME,
    max_tokens: int = 1024, # Можна налаштувати
) -> Union[str, None]:
    """
    Calls the OpenAI GPT Vision API.

    Args:
        base64_image: The base64 encoded image string.
        prompt: The prompt to send to the model.
        model: The GPT model to use.
        max_tokens: The maximum number of tokens for the response.

    Returns:
        The text content from the API response, or None if an error occurs.
    """
    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_OPENAI_API_KEY_HERE":
        logger.error("OpenAI API key is not configured for Vision (beta) call.")
        return "Помилка: API ключ OpenAI не налаштовано."

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            }
        ],
        "max_tokens": max_tokens,
    }

    try:
        async with aiohttp.ClientSession() as session:
            logger.info(f"Sending Vision API request. Model: {model}. Prompt: '{prompt[:70]}...'")
            async with session.post(
                OPENAI_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS
            ) as response:
                response_data = await response.json()
                if response.status == 200:
                    content = response_data.get("choices", [{}])[0].get("message", {}).get("content")
                    if content:
                        logger.info("Vision API call successful.")
                        return content.strip()
                    logger.error(f"Vision API response structure unexpected: {response_data}")
                    return "Помилка: Не вдалося отримати відповідь від моделі."
                error_details = response_data.get("error", {}).get("message", str(response_data))
                logger.error(f"Vision API request failed. Status: {response.status}, Details: {error_details}")
                return f"Помилка API ({response.status}): {error_details}"
    except aiohttp.ClientError as e:
        logger.error(f"HTTP error during Vision API call: {e}")
        # tenacity
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during Vision API call: {e}")
        return "Сталася непередбачена помилка під час звернення до Vision API."


@router.message(Command("vision_beta"))
async def cmd_vision_beta(message: Message, state: FSMContext):
    """
    Handles the /vision_beta command.
    Prompts the user to send an image for analysis.
    """
    await state.set_state(VisionBetaStates.AWAITING_IMAGE)
    await message.reply(
        "🔮 **Бета-версія Аналізу Зображень** 🔮\n\n"
        "Будь ласка, надішліть мені зображення (як фото або документ), і я спробую його проаналізувати. "
        "Це експериментальна функція, тому результати можуть бути не завжди ідеальними."
    )
    logger.info(f"User {message.from_user.id} initiated /vision_beta. Awaiting image.")


@router.message(VisionBetaStates.AWAITING_IMAGE, F.content_type.in_({'photo', 'document'}))
async def handle_vision_image(message: Message, state: FSMContext, bot: Bot):
    """
    Handles the image sent by the user when in AWAITING_IMAGE state.
    Processes the image using GPT Vision and sends back the analysis.
    """
    processing_message = await message.reply("⏳ Обробляю ваше зображення... Це може зайняти деякий час.")
    
    image_bytes_io = await download_image(message, bot)

    if not image_bytes_io:
        # download_image вже надіслав повідомлення про помилку, якщо вона була
        try: # Спробуємо видалити "Обробляю..."
            await bot.delete_message(chat_id=processing_message.chat.id, message_id=processing_message.message_id)
        except TelegramAPIError:
            pass # Якщо не вдалося, нічого страшного
        await state.clear() # Очищаємо стан, оскільки зображення не отримано
        return

    try:
        image_bytes_io.seek(0) # Переконуємося, що вказівник на початку
        base64_image_str = base64.b64encode(image_bytes_io.read()).decode("utf-8")
        
        # Використовуємо загальний промпт для бета-версії
        analysis_result = await call_openai_vision_api(
            base64_image=base64_image_str, prompt=GENERAL_VISION_PROMPT
        )

        if analysis_result:
            # Розділення довгої відповіді, якщо потрібно (Telegram має ліміт ~4096 символів)
            max_length = 4000 # Трохи менше ліміту для безпеки
            if len(analysis_result) > max_length:
                parts = [analysis_result[i:i + max_length] for i in range(0, len(analysis_result), max_length)]
                for i, part in enumerate(parts):
                    header = f"📄 **Аналіз зображення (частина {i+1}/{len(parts)}):**\n\n" if len(parts) > 1 else "📄 **Аналіз зображення:**\n\n"
                    await message.answer(f"{header}{part}", parse_mode=ParseMode.MARKDOWN) # Або HTML, якщо потрібно
            else:
                await message.answer(f"📄 **Аналіз зображення:**\n\n{analysis_result}", parse_mode=ParseMode.MARKDOWN)
        else:
            await message.reply("На жаль, не вдалося проаналізувати зображення. Спробуйте інше або пізніше.")

    except tenacity.RetryError:
        logger.error("GPT Vision API call failed after multiple retries.")
        await message.reply("Не вдалося з'єднатися з сервісом аналізу після декількох спроб. Будь ласка, спробуйте пізніше.")
    except Exception as e:
        logger.exception(f"Error processing vision image for user {message.from_user.id}: {e}")
        await message.reply("Сталася несподівана помилка під час аналізу зображення.")
    finally:
        try:
            await bot.delete_message(chat_id=processing_message.chat.id, message_id=processing_message.message_id)
        except TelegramAPIError:
            pass # Не критично, якщо не вдалося видалити
        await state.clear()


@router.message(VisionBetaStates.AWAITING_IMAGE)
async def handle_wrong_content_vision(message: Message, state: FSMContext):
    """
    Handles incorrect content type when AWAITING_IMAGE state is active.
    """
    await message.reply(
        "Будь ласка, надішліть зображення (фото або документ). "
        "Якщо хочете скасувати, просто проігноруйте це повідомлення або надішліть іншу команду."
    )
