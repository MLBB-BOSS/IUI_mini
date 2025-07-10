"""
Використовуємо останню версію Gemini 1.5 підчас внесення змін у коді не змінюй модель AI
Сервісний модуль для взаємодії з Google Gemini API.
Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini з використанням інструментів.
- Обробки специфічних помилок API.
- Формування "залізних" промптів для отримання пошукових результатів у форматі HTML.
"""
import logging
import os
from typing import Optional
import asyncio
from datetime import datetime, timezone

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError
from google.api_core import retry_async

# Імпортуємо логер, а ключ зчитуємо з os.getenv
from config import logger

# === КОНФІГУРАЦІЯ GEMINI API ===
try:
    GEMINI_API_KEY = os.getenv("API_Gemini")
    if not GEMINI_API_KEY:
        raise ValueError("Ключ API_Gemini не знайдено у змінних середовища.")
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Сервіс Google Gemini успішно сконфігуровано.")
except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка конфігурації Gemini: {e}")

class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini, що використовує інструмент пошуку Google.
    """
    def __init__(self):
        # ❗️ Оновлено ініціалізацію моделі для сумісності з версією бібліотеки
        self.model = genai.GenerativeModel(
            'models/gemini-1.5-flash-latest',
            tools=['google_search_retrieval'] # Явно вмикаємо пошук як рядок
        )
        logger.info("Модель для пошукових запитів: gemini-1.5-flash-latest (з інструментом Google Search)")

    @retry_async.AsyncRetry(predicate=retry_async.if_exception_type(GoogleAPIError), initial=1.0, maximum=10.0, multiplier=2.0)
    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini з використанням "залізного" промпту.

        Args:
            user_query: Запит від користувача.
            user_name: Ім'я користувача для персоналізації.

        Returns:
            Пряма відповідь від моделі або повідомлення про помилку.
        """
        if "яка сьгодні дата" in user_query.lower() or "яка дата" in user_query.lower():
            current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            return f"Сьогодні {current_date}, {user_name}! 😊"

        if len(user_query) > 1000:
            logger.warning(f"Запит від {user_name} занадто довгий: {len(user_query)} символів")
            return f"Вибач, {user_name}, твій запит занадто довгий. Скороти до 1000 символів."

        # ❗️ Оновлено промпт для використання HTML-тегів
        prompt = f"""
        **ЗАВДАННЯ:** Ти — високопродуктивний пошуковий двигун на базі AI. Ти ПОВИНЕН використовувати наданий інструмент Google Search для доступу до актуальної інформації. Твоє завдання — надати пряму, фактичну відповідь на запит користувача.

        **КОНТЕКСТ:**
        - Користувач: {user_name}
        - Запит користувача: "{user_query}"

        **КРИТИЧНІ ІНСТРУКЦІЇ:**
        1. **ПОШУК В ІНТЕРНЕТІ:** Завжди використовуй інструмент Google Search. Це обов'язково.
        2. **ПРЯМА ВІДПОВІДЬ:** Негайно надай відповідь на запит. Не пропонуй користувачеві шукати інформацію деінде.
        3. **ЗАБОРОНА ВІДМОВИ:** Категорично заборонено писати фрази типу "Я не маю доступу до інформації в реальному часі". Ти ПОВИНЕН надати відповідь на основі пошуку.
        4. **ФОРМАТУВАННЯ (HTML):** Відповідь має бути чіткою, структурованою, українською мовою. Використовуй HTML-теги для форматування: `<b>` для жирного шрифту, `<i>` для курсиву, `<code>` для коду, `<ul>` та `<li>` для списків. НЕ ВИКОРИСТОВУЙ MARKDOWN.
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
            if "quota" in str(e).lower():
                logger.info(f"Quota exceeded, waiting 35 seconds for retry...")
                await asyncio.sleep(35)
                return await self.get_search_response(user_query, user_name)
            return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
