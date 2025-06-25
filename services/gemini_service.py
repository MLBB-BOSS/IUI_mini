"""
Сервісний модуль для взаємодії з Google Gemini API.

Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- Обробки специфічних помилок API.
- Формування "залізних" промптів для отримання пошукових результатів.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

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
except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка конфігурації Gemini: {e}")


class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini, що використовує потужні промпти.
    """
    def __init__(self):
        # 🔽 ВИПРАВЛЕНО: Перейшли на 'flash' модель для вищих лімітів на безкоштовному тарифі
        self.model = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info(f"Модель для пошукових запитів: gemini-1.5-flash-latest (оптимізовано для тестування)")

    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini з використанням "залізного" промпту.

        Args:
            user_query: Запит від користувача.
            user_name: Ім'я користувача для персоналізації.

        Returns:
            Пряма відповідь від моделі або повідомлення про помилку.
        """
        # 🔽 ВИПРАВЛЕНО: Створюємо значно більш потужний та директивний промпт.
        # Ми прямо наказуємо моделі, як діяти, і забороняємо відмовлятися.
        prompt = f"""
        **ЗАВДАННЯ:** Ти — високопродуктивний пошуковий двигун на базі AI. Твоє завдання — надати пряму, фактичну відповідь на запит користувача, використовуючи твої найсвіжіші дані.

        **КОНТЕКСТ:**
        - Користувач: {user_name}
        - Поточна дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
        - Запит користувача: "{user_query}"

        **КРИТИЧНІ ІНСТРУКЦІЇ:**
        1. **ПРЯМА ВІДПОВІДЬ:** Негайно надай відповідь на запит. Не пропонуй користувачеві шукати інформацію деінде. ТИ і є пошуковий інструмент.
        2. **ЗАБОРОНА ВІДМОВИ:** Категорично заборонено писати фрази типу "Я не маю доступу до інформації в реальному часі", "Я не можу переглядати інтернет", "Перевірте офіційні джерела". Ти ПОВИНЕН надати відповідь на основі своїх знань.
        3. **АКТУАЛЬНІСТЬ:** Використовуй найновішу інформацію, доступну тобі. Якщо запит стосується останніх подій (наприклад, "останні зміни балансу"), твоя відповідь має відображати це.
        4. **ФОРМАТУВАННЯ:** Відповідь має бути чіткою, структурованою, українською мовою. Використовуй Markdown (жирний шрифт, списки) для покращення читабельності.

        **ВИКОНАЙ ЗАВДАННЯ.**
        """
        try:
            logger.info(f"Надсилаю запит до Gemini для користувача {user_name}: '{user_query[:60]}...'")
            
            response = await self.model.generate_content_async(prompt)
            
            logger.info(f"Успішно отримано відповідь від Gemini для {user_name}.")
            return response.text

        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
