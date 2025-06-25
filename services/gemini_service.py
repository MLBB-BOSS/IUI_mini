"""
Сервісний модуль для взаємодії з Google Gemini API.
Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- Обробки специфічних помилок API.
- Формування "залізних" промптів для отримання пошукових результатів.
"""
import logging
import os
from typing import Optional

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError
from google.api_core import retry

# Імпортуємо логер, а ключ зчитуємо з os.getenv
from config import logger

# === КОНФІГУРАЦІЯ GEMINI API ===
try:
    GEMINI_API_KEY = os.getenv('API_Gemini')
    if not GEMINI_API_KEY:
        raise ValueError("Ключ API_Gemini не знайдено у змінних середовища.")
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Сервіс Google Gemini успішно сконфігуровано.")
except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка конфігурації Gemini: {e}")

class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini, що використовує потужні промпти.
    """
    def __init__(self):
        self.model = genai.GenerativeModel('models/gemini-2.5-pro')
        logger.info("Модель для пошукових запитів: gemini-2.5-pro (з підтримкою Deep Research)")

    @retry.Retry(predicate=retry.if_exception_type(GoogleAPIError), initial=1.0, maximum=10.0, multiplier=2.0)
    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini з використанням "залізного" промпту.

        Args:
            user_query: Запит від користувача.
            user_name: Ім'я користувача для персоналізації.

        Returns:
            Пряма відповідь від моделі або повідомлення про помилку.
        """
        if len(user_query) > 1000:
            logger.warning(f"Запит від {user_name} занадто довгий: {len(user_query)} символів")
            return f"Вибач, {user_name}, твій запит занадто довгий. Скороти до 1000 символів."

        prompt = f"""
        **ЗАВДАННЯ:** Ти — високопродуктивний пошуковий двигун на базі AI з доступом до Google Search. Твоє завдання — надати пряму, фактичну відповідь на запит користувача, використовуючи найсвіжіші дані з інтернету.

        **КОНТЕКСТ:**
        - Користувач: {user_name}
        - Запит користувача: "{user_query}"

        **КРИТИЧНІ ІНСТРУКЦІЇ:**
        1. **ПОШУК В ІНТЕРНЕТІ:** Використовуй Google Search для знаходження актуальної інформації. Цитуй джерела, якщо можливо.
        2. **ПРЯМА ВІДПОВІДЬ:** Негайно надай відповідь на запит. Не пропонуй користувачеві шукати інформацію деінде.
        3. **ЗАБОРОНА ВІДМОВИ:** Категорично заборонено писати фрази типу "Я не маю доступу до інформації в реальному часі". Ти ПОВИНЕН надати відповідь.
        4. **ФОРМАТУВАННЯ:** Відповідь має бути чіткою, структурованою, українською мовою. Використовуй Markdown (жирний шрифт, списки) для покращення читабельності.
        5. **ТЕРМІНОЛОГІЯ MLBB:** Використовуй терміни Mobile Legends, як-от "паті", "мід", "танк", якщо запит стосується гри.

        **ВИКОНАЙ ЗАВДАННЯ.**
        """
        try:
            logger.info(f"Надсилаю запит до Gemini для користувача {user_name}: '{user_query[:60]}...'")
            response = await self.model.generate_content_async(prompt)
            logger.info(f"Успішно отримано відповідь від Gemini для {user_name}. Response length: {len(response.text) if response.text else 0}")
            return response.text.strip() if response.text else f"Вибач, {user_name}, не вдалося отримати відповідь."
        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
