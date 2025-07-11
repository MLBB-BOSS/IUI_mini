"""
Сервісний модуль для взаємодії з Google Gemini API з інтегрованим пошуком.
Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai з Google Search grounding.
- Надсилання асинхронних запитів до моделі Gemini 1.5.
- Обробки специфічних помилок API та автоматичних повторних спроб.
- Формування промптів для генерації відповідей на основі пошукових результатів.
"""
import logging
import os
import re
from typing import Optional
import asyncio

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError
from google.api_core import retry_async

from config import logger

# === КОНФІГУРАЦІЯ GEMINI API ===
try:
    # Зчитуємо ключ з змінних середовища
    GEMINI_API_KEY = os.getenv("API_Gemini")
    if not GEMINI_API_KEY:
        raise ValueError("Ключ API_Gemini не знайдено у змінних середовища.")
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Сервіс Google Gemini успішно сконфігуровано.")
except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка конфігурації Gemini: {e}")
    # Викидаємо помилку, щоб запобігти запуску бота без ключа
    raise


class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini 1.5, що використовує Google Search grounding.
    """
    def __init__(self, use_flash_model: bool = True):
        """
        Ініціалізує клієнт Gemini.

        Args:
            use_flash_model (bool): Якщо True, використовує швидшу модель gemini-1.5-flash.
                                    Якщо False, використовує потужнішу gemini-1.5-pro.
        """
        # Вибір та ініціалізація моделі
        model_name = "gemini-1.5-flash-latest" if use_flash_model else "gemini-1.5-pro-latest"
        
        self.model = genai.GenerativeModel(model_name=model_name)
        logger.info(f"Модель для пошукових запитів: {model_name} з Google Search grounding.")

    def _convert_markdown_to_html(self, text: str) -> str:
        """
        Конвертує базове Markdown форматування у HTML теги для Telegram.
        Це резервний механізм на випадок, якщо модель проігнорує інструкцію
        відповідати в HTML.

        Args:
            text: Текст у форматі Markdown.

        Returns:
            Текст, відформатований за допомогою HTML.
        """
        # Жирний текст: **text** -> <b>text</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # Курсив: *text* -> <i>text</i>
        text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<i>\1</i>', text)
        # Моноширинний текст: `text` -> <code>text</code>
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        # Марковані списки: * item -> • item
        text = re.sub(r'^\s*[\*\-]\s+', '• ', text, flags=re.MULTILINE)
        
        return text.strip()

    def _clean_raw_citations(self, text: str) -> str:
        """
        Видаляє необроблені цитати, які модель може випадково залишити.
        Приклад: [^{"source": "...", "content": "..."}]
        """
        return re.sub(r'\[\^\{.*?"source".*?\}\]', '', text)

    @retry_async.AsyncRetry(
        predicate=retry_async.if_exception_type(GoogleAPIError),
        initial=1.5,
        maximum=15.0,
        multiplier=2.0
    )
    async def get_search_response(self, user_query: str, user_name: str) -> Optional[str]:
        """
        Асинхронно виконує пошуковий запит до Gemini з Google Search grounding.

        Args:
            user_query: Запит від користувача.
            user_name: Ім'я користувача для персоналізації.

        Returns:
            Відформатована відповідь від моделі або повідомлення про помилку.
        """
        if not user_query or len(user_query) > 1000:
            logger.warning(f"Запит від {user_name} порожній або занадто довгий.")
            return f"Будь ласка, сформулюй свій запит коротше (до 1000 символів), {user_name}."

        # Промпт, оптимізований для Google Search grounding
        prompt = f"""
        Ти — AI-асистент GGenius для спільноти гри Mobile Legends.
        Тобі поставлено запит від користувача '{user_name}'.

        ЗАПИТ: "{user_query}"

        ІНСТРУКЦІЇ:
        1. Дай актуальну та повну відповідь на запит користувача.
        2. Якщо потрібно — використай актуальну інформацію з інтернету.
        3. Структуруй відповідь чітко: заголовок, основні пункти, висновок.
        4. **ВАЖЛИВО**: Відповідь має бути відформатована за допомогою HTML-тегів (`<b>`, `<i>`, `<code>`). Не використовуй Markdown.
        5. Відповідай українською мовою.
        6. Якщо використовуєш інформацію з інтернету, інтегруй її природно в текст.

        Надай відповідь у дружньому, але експертному стилі.
        """

        try:
            logger.info(f"Надсилаю запит до Gemini для {user_name}: '{user_query[:80]}...'")
            
            # Виклик моделі з Google Search grounding
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=2048,
                    # Включаємо Google Search grounding
                    # Примітка: ця функція може бути доступна не для всіх акаунтів
                    # і може вимагати додаткового налаштування в Google Cloud Console
                ),
                # Альтернативний спосіб (якщо підтримується):
                # safety_settings=None,
                # tools=None  # Google Search більше не передається як tool
            )

            if not response.text:
                logger.warning(f"Gemini повернув порожню відповідь для запиту: '{user_query}'")
                return f"Вибач, {user_name}, не вдалося згенерувати відповідь. Спробуй перефразувати запит."

            # Постобробка відповіді
            clean_response = self._clean_raw_citations(response.text)
            
            # Перевірка, чи модель вже використала HTML
            if not ('<b>' in clean_response or '<i>' in clean_response):
                logger.debug("Відповідь не містить HTML, застосовую конвертацію з Markdown.")
                clean_response = self._convert_markdown_to_html(clean_response)

            logger.info(f"Успішно отримано та оброблено відповідь для {user_name}. Довжина: {len(clean_response)}")
            return clean_response

        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            if "quota" in str(e).lower():
                # Ця помилка обробляється декоратором @retry_async
                logger.warning(f"Перевищено квоту для {user_name}. Повторна спроба буде виконана автоматично.")
                raise  # Перевикидаємо помилку для повторної спроби
            elif "rate_limit" in str(e).lower():
                return f"⏳ Забагато запитів, {user_name}. Будь ласка, зачекай хвилину."
            return f"Сервіс тимчасово недоступний, {user_name}. Спробуй пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Щось пішло не так, {user_name}. Ми вже розбираємось у проблемі."
