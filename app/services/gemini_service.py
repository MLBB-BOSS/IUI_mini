import logging
import io
from typing import List, Dict, Any, Tuple

from PIL import Image
import google.generativeai as genai
from google.generativeai.types import generation_types, content_types

from app.settings import settings

# Налаштування клієнта Gemini API винесено в окрему функцію для чистоти
def configure_gemini():
    """
    Configures the Gemini API client with the API key from settings.
    Raises:
        ValueError: If the GEMINI_API_KEY is not found in the settings.
    """
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
    except AttributeError:
        error_msg = "GEMINI_API_KEY not found in settings. Please check your configuration."
        logging.critical(error_msg)
        # Зупиняємо програму, якщо ключа немає, бо без нього бот непрацездатний
        raise ValueError(error_msg)

# Викликаємо конфігурацію при завантаженні модуля
configure_gemini()

# Конфігурації моделі залишаються без змін
generation_config = {
    "temperature": 0.8,
    "top_p": 1,
    "top_k": 32,
    "max_output_tokens": 8192, # Збільшено для довших відповідей
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]

# Ініціалізуємо модель з конфігураціями
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
    safety_settings=safety_settings
)

async def fetch_gemini_response(
    history: List[Dict[str, Any]],
    query: str,
    image_data: bytes | None = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Асинхронно отримує відповідь від Gemini API, використовуючи надану історію.

    Args:
        history: Історія розмови у форматі, сумісному з Gemini API.
        query: Новий текстовий запит від користувача.
        image_data: Байтові дані зображення (якщо є).

    Returns:
        Кортеж, що містить:
        - Текстову відповідь від моделі Gemini.
        - Оновлену історію розмови.
    """
    try:
        chat_session = model.start_chat(history=history)
        
        prompt_parts = []
        if image_data:
            try:
                img = Image.open(io.BytesIO(image_data))
                prompt_parts.append(img)
            except Exception as e:
                logging.error(f"Error processing image: {e}")
                return "Вибачте, не вдалося обробити надане зображення.", history
        
        prompt_parts.append(query)
        
        response = await chat_session.send_message_async(prompt_parts)

        # Оновлюємо історію: додаємо запит користувача та відповідь моделі
        # Важливо: зберігаємо точну структуру, яку очікує API
        updated_history = chat_session.history
        
        return response.text, updated_history

    except generation_types.StopCandidateException as e:
        logging.warning(f"Response stopped due to StopCandidateException: {e}")
        return "Моя відповідь була зупинена. Можливо, запит був неповним.", history
    except generation_types.BlockedPromptException as e:
        logging.warning(f"Prompt blocked due to safety settings: {e}")
        return "Ваш запит було заблоковано через політику безпеки. Будь ласка, перефразуйте його.", history
    except Exception as e:
        logging.error(f"An unknown error occurred with Gemini API: {e}", exc_info=True)
        return "Вибачте, сталася невідома помилка під час звернення до Gemini. Спробуйте пізніше.", history
