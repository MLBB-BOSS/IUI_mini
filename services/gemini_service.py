"""
Використовуємо останню версію Gemini 2.5 підчас внесення змін у коді не змінюй модель AI
Сервісний модуль для взаємодії з Google Gemini API.
Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- Обробки специфічних помилок API.
- Формування "залізних" промптів для отримання пошукових результатів.
"""
import logging
import os
import re
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
        # Налаштовуємо модель з підтримкою пошуку
        self.model = genai.GenerativeModel(
            'models/gemini-2.5-pro',
            tools='google_search_retrieval'  # Додаємо інструмент пошуку
        )
        logger.info("Модель для пошукових запитів: gemini-2.5-pro (з підтримкою Google Search)")

    def _convert_markdown_to_html(self, text: str) -> str:
        """
        Конвертує Markdown форматування у HTML для Telegram.
        
        Args:
            text: Текст у форматі Markdown
            
        Returns:
            Текст у форматі HTML
        """
        # Заголовки
        text = re.sub(r'^### (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^# (.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        
        # Жирний текст
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
        
        # Курсив
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
        
        # Код
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        
        # Списки
        text = re.sub(r'^\* (.+)$', r'• \1', text, flags=re.MULTILINE)
        text = re.sub(r'^\- (.+)$', r'• \1', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\. (.+)$', r'• \1', text, flags=re.MULTILINE)
        
        # Посилання [text](url) -> text
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1', text)
        
        # Видаляємо блоки коду
        text = re.sub(r'```[\s\S]*?```', '', text)
        
        return text.strip()

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
        # Обробка простих запитів
        if "яка сьгодні дата" in user_query.lower() or "яка дата" in user_query.lower():
            current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            return f"Сьогодні {current_date}, {user_name}! 😊"

        if len(user_query) > 1000:
            logger.warning(f"Запит від {user_name} занадто довгий: {len(user_query)} символів")
            return f"Вибач, {user_name}, твій запит занадто довгий. Скороти до 1000 символів."

        prompt = f"""
        **ЗАВДАННЯ:** Ти — високопродуктивний пошуковий AI з прямим доступом до Google Search. Твоє завдання — знайти та надати найсвіжішу інформацію з інтернету.

        **КОНТЕКСТ:**
        - Користувач: {user_name}
        - Запит користувача: "{user_query}"
        - Поточна дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

        **КРИТИЧНІ ІНСТРУКЦІЇ:**
        1. **ОБОВ'ЯЗКОВО ВИКОРИСТАЙ GOOGLE SEARCH** для пошуку актуальної інформації по запиту.
        2. **АНАЛІЗУЙ РЕЗУЛЬТАТИ:** Вибери найрелевантніші та найсвіжіші джерела.
        3. **ЦИТУЙ ДЖЕРЕЛА:** Вказуй назви сайтів або публікацій звідки взята інформація.
        4. **ФОКУС НА MOBILE LEGENDS:** Якщо запит стосується MLBB, шукай на офіційних сайтах, форумах, YouTube.
        5. **СТРУКТУРА ВІДПОВІДІ:**
           - Коротке резюме (1-2 речення)
           - Основна інформація по пунктах
           - Джерела інформації
        6. **БЕЗ ВІДМОВ:** Завжди надавай відповідь на основі знайденого.

        **ВИКОНАЙ ПОШУК ТА НАДАЙ ВІДПОВІДЬ:**
        """
        
        try:
            logger.info(f"Надсилаю запит до Gemini для користувача {user_name}: '{user_query[:60]}...'")
            
            # Генеруємо відповідь з використанням пошуку
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=2048,
                )
            )
            
            if response.text:
                # Конвертуємо Markdown в HTML
                html_response = self._convert_markdown_to_html(response.text)
                logger.info(f"Успішно отримано та сконвертовано відповідь для {user_name}. Length: {len(html_response)}")
                return html_response
            else:
                return f"Вибач, {user_name}, не вдалося отримати відповідь від пошуку."
                
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
