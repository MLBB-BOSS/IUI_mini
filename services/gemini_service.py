"""
Сервісний модуль для взаємодії з Google Gemini API.

Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- 🆕 Надання моделі інструменту "Google Search" для доступу до Інтернету в реальному часі.
- Обробки специфічних помилок API.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

import google.generativeai as genai
# 🔽 ІМПОРТУЄМО НОВІ ТИПИ ДЛЯ РОБОТИ З ІНСТРУМЕНТАМИ
from google.generativeai.types import HarmCategory, HarmBlockThreshold, Tool
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
        # 🔽 ВИЗНАЧАЄМО НАШ ІНСТРУМЕНТ "ПОШУК В GOOGLE"
        # Ми не пишемо код для пошуку, ми лише описуємо інструмент для моделі.
        # Google API сам виконає пошук, коли модель попросить.
        self.search_tool = Tool(
            google_search_retrieval={}
        )

        # Ініціалізуємо модель. Ми будемо використовувати 'gemini-1.5-flash'
        # оскільки вона швидка і підтримує інструменти.
        self.model = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info(f"Модель для пошуку: gemini-1.5-flash-latest з інструментом Google Search.")

    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini, надаючи їй доступ до Google Search.

        Args:
            user_query: Запит від користувача.
            user_name: Ім'я користувача для персоналізації.

        Returns:
            Пряма, актуальна відповідь від моделі або повідомлення про помилку.
        """
        # Промпт залишається важливим, він керує тим, ЯК модель синтезує знайдену інформацію.
        prompt = f"""
        **ЗАВДАННЯ:** Ти — AI-асистент для гравців Mobile Legends. Твоє завдання — надати вичерпну та актуальну відповідь на запит користувача, використовуючи наданий тобі інструмент "Google Search" для доступу до інформації в реальному часі.

        **КОНТЕКСТ:**
        - Користувач: {user_name}
        - Поточна дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
        - Запит користувача: "{user_query}"

        **КРИТИЧНІ ІНСТРУКЦІЇ:**
        1. **ВИКОРИСТОВУЙ ПОШУК:** Для відповідей, що вимагають свіжої інформації (оновлення, патчі, новини), ОБОВ'ЯЗКОВО використовуй інструмент "Google Search".
        2. **ПРЯМА ВІДПОВІДЬ:** Надай відповідь безпосередньо. Не посилайся на джерела, а синтезуй інформацію з них у єдину, чітку відповідь.
        3. **ЗАБОРОНА ВІДМОВИ:** Категорично заборонено писати фрази "Я не маю доступу до інтернету". Ти МАЄШ цей доступ через наданий інструмент.
        4. **ФОРМАТУВАННЯ:** Відповідь має бути українською мовою, добре структурованою. Використовуй Markdown.

        **ВИКОНАЙ ЗАВДАННЯ.**
        """
        try:
            logger.info(f"Надсилаю запит до Gemini (з інструментом пошуку) для {user_name}: '{user_query[:60]}...'")
            
            # 🔽 КЛЮЧОВА ЗМІНА: Передаємо наш інструмент у виклик API
            response = await self.model.generate_content_async(
                prompt,
                tools=[self.search_tool]
            )
            
            logger.info(f"Успішно отримано відповідь від Gemini (після пошуку) для {user_name}.")
            return response.text

        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."
