"""
Сервісний модуль для взаємодії з Google Vertex AI.
Цей файл інкапсулює всю логіку для:
- Роботи з Gemini через продакшн-ендпоінт Vertex AI, використовуючи платний тариф.
- Надійної активації вбудованого інструменту "Google Search".
- Реалізації експоненційної затримки (Exponential Backoff) для повторних спроб.
"""
import logging
import os
from typing import Optional

# Використовуємо правильні імпорти з Vertex AI SDK
import vertexai
from vertexai.generative_models import GenerativeModel, Tool
from google.api_core.exceptions import ResourceExhausted, GoogleAPIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import logger

# === ІНІЦІАЛІЗАЦІЯ VERTEX AI ===
try:
    GOOGLE_CLOUD_PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
    if not GOOGLE_CLOUD_PROJECT_ID:
        raise ValueError("Змінна середовища GOOGLE_CLOUD_PROJECT_ID не встановлена!")
    
    vertexai.init(project=GOOGLE_CLOUD_PROJECT_ID, location="us-central1")
    logger.info(f"✅ Сервіс Vertex AI успішно ініціалізовано для проєкту '{GOOGLE_CLOUD_PROJECT_ID}'.")

except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка ініціалізації Vertex AI: {e}")
    raise

class GeminiSearch:
    def __init__(self):
        # 🔽 ВИПРАВЛЕНО: Забираємо пробіл з назви функції.
        self.model = GenerativeModel(
            "gemini-1.5-pro-latest",
            tools=[Tool.from_google_search_retrieval()] # Правильна назва: from_google_search_retrieval
        )
        logger.info(f"Модель gemini-1.5-pro-latest (Vertex AI) ініціалізовано з активованим Google Search.")

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(ResourceExhausted),
        before_sleep=lambda retry_state: logger.warning(f"Перевищено квоту Vertex AI, повторна спроба через {retry_state.next_action.sleep:.0f}с...")
    )
    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        prompt = f"User: {user_name}, Request: {user_query}. Provide a direct, factual answer in Ukrainian using Google Search. Do not refuse. Format with Markdown."
        try:
            logger.info(f"Надсилаю запит до Vertex AI для {user_name}: '{user_query[:60]}...'")
            response = await self.model.generate_content_async(prompt)
            logger.info(f"Успішно отримано відповідь від Vertex AI для {user_name}.")
            return response.text
        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Vertex AI: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до сервісу Google."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Vertex AI: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так."
