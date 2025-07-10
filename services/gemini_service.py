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
        # Налаштовуємо модель без tools параметра
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        logger.info("Модель для пошукових запитів: gemini-2.5-pro")

    def _convert_markdown_to_html(self, text: str) -> str:
        """
        Конвертує Markdown форматування у HTML для Telegram.
        
        Args:
            text: Текст у форматі Markdown
            
        Returns:
            Текст у форматі HTML
        """
        # Заголовки - спочатку ### потім ## і #
        text = re.sub(r'^###\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^##\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^#\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        
        # Жирний текст (обробляємо обидва варіанти)
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
        
        # Курсив (уникаємо конфлікту з жирним)
        text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
        text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)
        
        # Код
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        
        # Списки (маркеровані)
        text = re.sub(r'^\*\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        text = re.sub(r'^-\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        text = re.sub(r'^\+\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        
        # Нумеровані списки
        text = re.sub(r'^\d+\.\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        
        # Посилання [text](url) -> text
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        
        # Видаляємо блоки коду
        text = re.sub(r'```[\s\S]*?```', '', text)
        
        # Видаляємо зайві порожні рядки
        text = re.sub(r'\n{3,}', '\n\n', text)
        
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
        if "яка сьогодні дата" in user_query.lower() or "яка дата" in user_query.lower():
            current_date = datetime.now(timezone.utc).strftime('%d.%m.%Y')
            return f"Сьогодні <b>{current_date}</b>, {user_name}! 😊"

        if len(user_query) > 1000:
            logger.warning(f"Запит від {user_name} занадто довгий: {len(user_query)} символів")
            return f"Вибач, {user_name}, твій запит занадто довгий. Скороти до 1000 символів."

        # Оновлений промпт з інструкцією форматувати в HTML
        prompt = f"""
Ти — пошуковий AI асистент з актуальними знаннями про Mobile Legends: Bang Bang до січня 2025 року.

**КОНТЕКСТ:**
- Користувач: {user_name}
- Запит: "{user_query}"
- Дата: {datetime.now(timezone.utc).strftime('%d.%m.%Y')}

**ІНСТРУКЦІЇ:**
1. Надай актуальну інформацію на основі твоїх знань до січня 2025
2. Якщо запит стосується новин після січня 2025, чесно скажи про це
3. Фокусуйся на MLBB контенті: герої, предмети, патчі, мета, турніри
4. Структуруй відповідь чітко та зрозуміло
5. **ВАЖЛИВО**: НЕ використовуй Markdown форматування
6. Використовуй HTML теги: <b>жирний</b>, <i>курсив</i>, <code>код</code>

**СТРУКТУРА ВІДПОВІДІ:**
- Коротке резюме (1-2 речення)  
- Основна інформація по пунктах
- Якщо можливо, вкажи приблизні джерела

Надай відповідь українською мовою з HTML форматуванням:
"""
        
        try:
            logger.info(f"Надсилаю запит до Gemini для користувача {user_name}: '{user_query[:60]}...'")
            
            # Генеруємо відповідь
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=2048,
                    top_p=0.9,
                    top_k=40,
                )
            )
            
            if response.text:
                # Перевіряємо чи відповідь вже в HTML форматі
                if '<b>' in response.text or '<i>' in response.text:
                    # Вже HTML, повертаємо як є
                    clean_response = response.text.strip()
                else:
                    # Конвертуємо Markdown в HTML
                    clean_response = self._convert_markdown_to_html(response.text)
                
                logger.info(f"Успішно отримано відповідь для {user_name}. Length: {len(clean_response)}")
                return clean_response
            else:
                return f"Вибач, {user_name}, не вдалося отримати відповідь."
                
        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            if "quota" in str(e).lower():
                logger.info(f"Quota exceeded, waiting 35 seconds for retry...")
                await asyncio.sleep(35)
                return await self.get_search_response(user_query, user_name)
            elif "rate_limit" in str(e).lower():
                return f"Вибач, {user_name}, занадто багато запитів. Спробуй через хвилину. ⏳"
            return f"Вибач, {user_name}, сталась помилка сервісу. Спробуй пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло не так. Ми вже досліджуємо проблему."
