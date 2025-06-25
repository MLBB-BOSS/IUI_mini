"""
Сервісний модуль для взаємодії з Google Gemini API.

Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- Обробки специфічних помилок API.
- Формування промптів для отримання пошукових результатів.
"""
import logging
from typing import Optional

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

# Імпортуємо конфігурацію та логер з головного файлу
from config import GEMINI_API_KEY, logger

# === КОНФІГУРАЦІЯ GEMINI API ===
try:
    if not GEMINI_API_KEY:
        raise ValueError("Ключ GEMINI_API_KEY не знайдено у змінних середовища.")
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Сервіс Google Gemini успішно сконфігуровано.")
except ValueError as e:
    logger.error(f"❌ Помилка конфігурації Gemini: {e}")
    # У разі відсутності ключа, функціонал буде недоступний
    # Але бот продовжить працювати з іншими сервісами.


class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini Pro для пошукових запитів.
    """
    def __init__(self):
        # Обираємо найпотужнішу модель для якісного пошуку та аналізу
        # У майбутньому тут можна буде легко перемкнутись на 2.5
        self.model = genai.GenerativeModel('gemini-1.5-pro-latest')
        logger.info(f"Модель для пошукових запитів: gemini-1.5-pro-latest (жорстко задано)")

    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini.

        Args:
            user_query: Запит від користувача.
            user_name: Ім'я користувача для персоналізації.

        Returns:
            Відформатована відповідь від моделі або None у разі помилки.
        """
        # Створюємо просунутий промпт, щоб скерувати модель саме на пошук
        prompt = f"""
        Ти — експертний пошуковий AI-асистент. Твоє завдання — знайти найсвіжішу та найрелевантнішу інформацію в Інтернеті на запит користувача.
        Користувач ({user_name}) запитує: "{user_query}"

        Інструкції:
        1. Проаналізуй запит і визнач ключові теми для пошуку.
        2. Знайди найактуальніші дані (новини, патчі, статті, оновлення за останній час).
        3. Надай відповідь українською мовою.
        4. Відповідь має бути структурованою, чіткою та по суті. Використовуй маркдаун для форматування (жирний шрифт, списки).
        5. Не вигадуй інформацію. Якщо нічого не знайдено, повідом про це.
        """
        try:
            logger.info(f"Надсилаю запит до Gemini для користувача {user_name}: '{user_query[:60]}...'")
            
            # Використовуємо асинхронний метод для генерації контенту
            response = await self.model.generate_content_async(prompt)
            
            logger.info(f"Успішно отримано відповідь від Gemini для {user_name}.")
            return response.text

        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
