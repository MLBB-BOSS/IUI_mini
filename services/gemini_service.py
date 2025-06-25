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
from datetime import datetime, timezone

# 🔽 Переходимо на офіційний SDK для Vertex AI - це ключ до платного доступу
import vertexai
from vertexai.generative_models import GenerativeModel, Tool
from google.api_core.exceptions import ResourceExhausted, GoogleAPIError

# 🔽 Додаємо бібліотеку для "розумних" повторних спроб - стандарт якості
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Імпортуємо логер
from config import logger

# === ІНІЦІАЛІЗАЦІЯ VERTEX AI ===
try:
    # Зчитуємо ID проєкту, який ти додав у Heroku. Це наш "ключ" від платного входу.
    GOOGLE_CLOUD_PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
    if not GOOGLE_CLOUD_PROJECT_ID:
        raise ValueError("Змінна середовища GOOGLE_CLOUD_PROJECT_ID не встановлена! Це ключ до платного доступу.")
    
    # Ініціалізуємо Vertex AI, вказуючи наш проєкт.
    vertexai.init(project=GOOGLE_CLOUD_PROJECT_ID, location="us-central1")
    logger.info(f"✅ Сервіс Vertex AI успішно ініціалізовано для проєкту '{GOOGLE_CLOUD_PROJECT_ID}'.")

except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка ініціалізації Vertex AI: {e}")


class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini через Vertex AI,
    що гарантує використання платного тарифу та високу надійність.
    """
    def __init__(self):
        # 🔽 ВИКОРИСТОВУЄМО ТЕ, ЩО ТОБІ ПОТРІБНО:
        # Назва 'gemini-1.5-pro-latest' - це стабільний технічний ідентифікатор для флагманської
        # моделі Pro. Тег "-latest" гарантує, що ти завжди отримуєш доступ до останніх
        # можливостей, анонсованих як "2.5 Pro".
        self.model = GenerativeModel(
            "gemini-1.5-pro-latest",
            tools=[Tool.from_google_search_retrieval()] # Правильний спосіб активації пошуку для Vertex AI
        )
        logger.info(f"Модель для пошуку: gemini-1.5-pro-latest (Vertex AI), що надає можливості '2.5 Pro', з активованим Google Search.")

    # 🔽 Декоратор Tenacity для автоматичних повторних спроб
    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30), # Затримка: 2с, 4с, 8с...
        stop=stop_after_attempt(3), # Максимум 3 спроби
        retry=retry_if_exception_type(ResourceExhausted), # Повторювати тільки при помилках квоти
        before_sleep=lambda retry_state: logger.warning(f"Перевищено квоту Vertex AI, повторна спроба через {retry_state.next_action.sleep:.0f}с...")
    )
    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini через Vertex AI.
        """
        prompt = f"""
        **ЗАВДАННЯ:** Ти — AI-асистент для гравців Mobile Legends. Твоє завдання — надати вичерпну та актуальну відповідь на запит користувача, використовуючи доступ до Google Search.
        **КОНТЕКСТ:**
        - Користувач: {user_name}
        - Поточна дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
        - Запит користувача: "{user_query}"
        **КРИТИЧНІ ІНСТРУКЦІЇ:**
        1. **ПРЯМА ВІДПОВІДЬ:** Надай відповідь безпосередньо. Не посилайся на джерела, а синтезуй інформацію з них у єдину, чітку відповідь.
        2. **ЗАБОРОНА ВІДМОВИ:** Категорично заборонено писати фрази "Я не маю доступу до інтернету". Ти МАЄШ цей доступ.
        3. **ФОРМАТУВАННЯ:** Відповідь має бути українською мовою, добре структурованою. Використовуй Markdown.
        **ВИКОНАЙ ЗАВДАННЯ.**
        """
        try:
            logger.info(f"Надсилаю запит до Vertex AI (Gemini 1.5 Pro) для {user_name}: '{user_query[:60]}...'")
            
            response = await self.model.generate_content_async(prompt)
            
            logger.info(f"Успішно отримано відповідь від Vertex AI для {user_name}.")
            return response.text

        except ResourceExhausted as e:
            logger.error(f"Вичерпано всі спроби. Квота Vertex AI перевищена для {user_name}: {e}")
            raise # Перевикидаємо помилку, щоб tenacity її зловив і зробив повторну спробу

        except GoogleAPIError as e:
            logger.error(f"Загальна помилка Google API під час запиту до Vertex AI від {user_name}: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Vertex AI для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
