"""
Утиліти для роботи з пошуковими запитами та результатами.
"""
import aiohttp
import json
from typing import Any
from config import logger


async def search_mlbb_info(query: str) -> list[dict[str, Any]] | None:
    """
    Альтернативний пошук інформації про MLBB через публічні API.
    
    Args:
        query: Пошуковий запит
        
    Returns:
        Список результатів пошуку або None
    """
    # Тут можна додати інтеграцію з:
    # - YouTube Data API для пошуку гайдів
    # - Reddit API для пошуку обговорень
    # - Custom scraper для офіційного сайту MLBB
    
    # Поки що повертаємо заглушку
    logger.info(f"Fallback search for: {query}")
    return None


def format_search_results(results: list[dict[str, Any]], user_name: str) -> str:
    """
    Форматує результати пошуку у HTML.
    
    Args:
        results: Список результатів
        user_name: Ім'я користувача
        
    Returns:
        Відформатований HTML текст
    """
    if not results:
        return f"Вибач, {user_name}, не знайшов інформації по твоєму запиту. 😔"
    
    formatted = [f"<b>🔍 Результати пошуку для {user_name}:</b>\n"]
    
    for i, result in enumerate(results[:5], 1):
        formatted.append(f"{i}. <b>{result.get('title', 'Без назви')}</b>")
        if snippet := result.get('snippet'):
            formatted.append(f"   {snippet}")
        if source := result.get('source'):
            formatted.append(f"   <i>Джерело: {source}</i>")
        formatted.append("")
    
    return "\n".join(formatted)
