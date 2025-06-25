# services/gemini_service.py

"""
Сервісний модуль для взаємодії з Google Gemini API.
Цей файл інкапсулює всю логіку для:
- Конфігурації клієнта google-genai.
- Надсилання асинхронних запитів до моделі Gemini.
- Обробки специфічних помилок API.
- Формування "залізних" промптів для отримання пошукових результатів.

Використовуємо останню версію Gemini 2.5.
"""
import logging
import os
from typing import Optional
import asyncio
from datetime import datetime, timezone

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError
from google.api_core import retry_async
# 🆕 Імпортуємо для детального дебагу викликів інструментів
from google.generativeai.types import FunctionCall, ToolOutput

# Імпортуємо логер з config.py
from config import logger # GOOGLE_CLOUD_PROJECT_ID не потрібен тут для genai.configure()

# === КОНФІГУРАЦІЯ GEMINI API ===
try:
    GEMINI_API_KEY = os.getenv('API_Gemini')
    if not GEMINI_API_KEY:
        raise ValueError("Ключ API_Gemini не знайдено у змінних середовища Heroku Config Vars.")

    # Конфігурація без явного Project ID у client_options, бо для API key це не типово
    # та може спричинити помилки, якщо API Endpoint сформований невірно.
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Сервіс Google Gemini успішно сконфігуровано.")
except (ValueError, ImportError) as e:
    logger.error(f"❌ Помилка конфігурації Gemini: {e}")

class GeminiSearch:
    """
    Асинхронний клієнт для роботи з Gemini, що використовує потужні промпти.
    """
    def __init__(self):
        # Модель з вбудованим Grounding (пошуком) автоматично вирішує, коли його використовувати.
        # Не потрібно явно вказувати tools=[] для вбудованого Google Search Tool.
        self.model = genai.GenerativeModel('models/gemini-2.5-pro')
        logger.info("Модель для пошукових запитів: gemini-2.5-pro (з потенційною підтримкою Google Search Grounding).")

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

            # Відправлення запиту до моделі.
            # Моделі типу Gemini 2.5 Pro з вбудованим Grounding (пошуком)
            # автоматично вирішують, коли його використовувати на основі промпту.
            response = await self.model.generate_content_async(prompt)

            # --- Дебаг логування для інструментів ---
            if response.candidates:
                logger.info(f"Отримано кандидати від Gemini. Кількість: {len(response.candidates)}")
                for i, candidate in enumerate(response.candidates):
                    logger.info(f"Кандидат {i+1}:")
                    if candidate.content:
                        for part in candidate.content.parts:
                            if isinstance(part, FunctionCall):
                                logger.info(f"  МОДЕЛЬ ВИКЛИКАЛА ІНСТРУМЕНТ: {part.name}(args={part.args})")
                                if part.name == 'search': # Якщо модель явно викликає інструмент "search"
                                    logger.info("  -> Модель спробувала використати вбудований Google Search.")
                            elif isinstance(part, ToolOutput):
                                logger.info(f"  РЕЗУЛЬТАТ ВИКЛИКУ ІНСТРУМЕНТА ({part.tool_name}): {str(part.result)[:200]}...") # Логуємо лише частину результату
                            else:
                                logger.info(f"  Отримано текстову частину відповіді. Довжина: {len(part.text) if part.text else 0}")
                    else:
                        logger.warning(f"Кандидат {i+1} не має вмісту (content). Finish reason: {candidate.finish_reason}")
            else:
                logger.warning(f"Response does not contain any candidates. Debug info: {response.to_dict()}")
            # --- Кінець дебаг логування ---

            final_response_text = ""
            if response.text:
                final_response_text = response.text.strip()
            elif response.candidates and response.candidates[0].finish_reason:
                final_response_text = (
                    f"Модель завершила генерацію з причиною: {response.candidates[0].finish_reason}. "
                    "Можливо, потрібна додаткова обробка або вона не змогла згенерувати повну відповідь."
                )
            else:
                final_response_text = f"Вибач, {user_name}, не вдалося отримати відповідь від Gemini. Немає тексту та незрозуміла причина завершення."


            logger.info(f"Успішно отримано відповідь від Gemini для {user_name}. Final response length: {len(final_response_text)}")
            return final_response_text
        except GoogleAPIError as e:
            logger.error(f"Помилка Google API під час запиту до Gemini від {user_name}: {e}")
            if "quota" in str(e).lower():
                logger.info(f"Quota exceeded. Please check your Google Cloud quotas. Error: {e}")
                # Можна додати await asyncio.sleep(35) якщо це дійсно тимчасове перевищення
                # Але для "постійних" помилок краще не зациклювати ретрай
                return f"Вибач, {user_name}, схоже, перевищено квоту запитів до Gemini. Будь ласка, спробуй пізніше або звернися до адміністратора. Деталі: {e}"
            elif "permission denied" in str(e).lower() or "unauthenticated" in str(e).lower():
                 logger.error(f"Помилка автентифікації/дозволів для Gemini API. Перевірте ключ та дозволи Project ID. Error: {e}")
                 return f"Вибач, {user_name}, сталася помилка з дозволами доступу до сервісу Gemini. Перевір налаштування API ключа та дозволи у Google Cloud."
            else:
                return f"Вибач, {user_name}, сталась помилка під час звернення до пошукового сервісу Google: {e}. Спробуй, будь ласка, пізніше."
        except Exception as e:
            logger.exception(f"Неочікувана помилка в сервісі Gemini для {user_name}: {e}")
            return f"Вибач, {user_name}, щось пішло зовсім не так. Ми вже досліджуємо проблему."

