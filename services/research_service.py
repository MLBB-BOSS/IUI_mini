"""
Сервіс для виконання глибоких досліджень за допомогою OpenAI.
"""
import asyncio
import logging
from openai import OpenAI
from typing import Dict, Any

from config import OPENAI_API_KEY

# Ініціалізуємо логер для цього модуля
logger = logging.getLogger(__name__)

# Налаштування клієнта для довгих запитів
client = OpenAI(api_key=OPENAI_API_KEY, timeout=3600.0)


class MLBBDeepResearch:
    """Керує створенням та виконанням завдань Deep Research."""

    def __init__(self, model: str = "o4-mini-deep-research"):
        """
        Ініціалізує сервіс з вказаною моделлю.

        Args:
            model (str): Назва моделі для дослідження.
        """
        self.model = model
        logger.info(f"MLBBDeepResearch service initialized with model: {self.model}")

    def _rewrite_prompt(self, user_query: str) -> str:
        """
        Перетворює запит користувача на детальний промпт для моделі.
        """
        logger.info(f"Rewriting prompt for query: '{user_query}'")
        rewritten_prompt = f"""
        Проведи глибоке дослідження на тему: '{user_query}'.
        Тема стосується гри Mobile Legends: Bang Bang.
        
        Твої завдання:
        1.  **Аналіз**: Проаналізуй тему, використовуючи веб-пошук для отримання актуальних даних.
        2.  **Структура**: Відповідь має бути структурована як звіт з чіткими заголовками (`<b>...</b>`), списками (`• ...`) та висновками.
        3.  **Джерела**: Пріоритезуй офіційні джерела, ігрові вікі (напр., Fandom), та популярні аналітичні сайти (напр., MLBB.GG). Включай посилання на джерела.
        4.  **Дані**: Використовуй конкретні цифри, статистику, порівняльні таблиці, якщо це доречно.
        5.  **Мова**: Відповідь надай українською мовою.
        6.  **Форматування**: Використовуй HTML теги для форматування (`<b>`, `<i>`, `<code>`).
        """
        return rewritten_prompt

    async def start_research_task(self, user_query: str) -> Dict[str, Any]:
        """
        Запускає асинхронне завдання для глибокого дослідження.
        """
        detailed_prompt = self._rewrite_prompt(user_query)

        logger.info(f"Starting deep research task with model '{self.model}'...")
        
        # Використовуємо asyncio.to_thread для запуску синхронного SDK в async-коді
        response = await asyncio.to_thread(
            client.responses.create,
            model=self.model,
            input=detailed_prompt,
            tools=[
                {"type": "web_search_preview"},
                {"type": "code_interpreter", "container": {"type": "auto"}},
            ],
        )
        
        logger.info(f"Deep research task with '{self.model}' completed.")
        return response.dict()
