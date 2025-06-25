"""
Сервісний модуль для взаємодії з Google Gemini API.

Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- 🆕 Активації вбудованого інструменту "Google Search" для доступу до Інтернету.
- Обробки специфічних помилок API.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

# Імпортуємо конфігурацію та логер
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
    Асинхронний клієнт для роботи з Gemini, що використовує "Tool Calling"
    для доступу до Google Search в реальному часі.
    """
    def __init__(self):
        # 🔽 КЛЮЧОВЕ ВИПРАВЛЕННЯ: Ми не створюємо інструмент вручну.
        # Ми вказуємо назву вбудованого інструменту ('google_search')
        # безпосередньо при ініціалізації моделі.
        self.model = genai.GenerativeModel(
            model_name='gemini-1.5-flash-latest',
            tools=['google_search'] # Ось і вся магія!
        )
        logger.info(f"Модель для пошуку: gemini-1.5-flash-latest з активованим інструментом Google Search.")

    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini. Модель автоматично
        вирішить, чи використовувати Google Search.
        """
        # Промпт залишається важливим, він керує тим, ЯК модель синтезує знайдену інформацію.
        prompt = f"""
        **ЗАВДАННЯ:** Ти — AI-асистент для гравців Mobile Legends. Твоє завдання — надати вичерпну та актуальну відповідь на запит користувача. Використовуй свої внутрішні знання та, за потреби, доступ до Google Search для отримання інформації в реальному часі.

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
            logger.info(f"Надсилаю запит до Gemini (з доступом до пошуку) для {user_name}: '{user_query[:60]}...'")
            
            # Тепер нам не потрібно передавати інструменти сюди, вони вже є частиною моделі
            response = await self.model.generate_content_async(prompt)
            
            logger.info(f"Успішно отримано відповідь від Gemini (після пошуку) для {user_name}.")
            return response.text

        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
