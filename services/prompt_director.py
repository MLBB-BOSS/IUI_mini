"""
Директор Промптів: "мозок" системи, що конструює системні промпти
на основі контексту.
"""
from typing import Any, Dict, List

from config import logger
from prompts.loader import PROMPT_LIBRARY
from services.context_engine import ContextVector

class PromptDirector:
    """
    Клас, що відповідає за динамічну збірку системних промптів
    з модульних фрагментів на основі вхідного контексту.
    """
    def __init__(self, prompt_library: Dict[str, Any]):
        """
        Ініціалізує директора, передаючи йому завантажену бібліотеку промптів.
        """
        if not prompt_library:
            logger.error("PromptDirector ініціалізовано з порожньою бібліотекою промптів!")
        self.library = prompt_library
        logger.info("✅ PromptDirector ініціалізовано з бібліотекою промптів.")

    def build_prompt(self, context: ContextVector) -> str:
        """
        Збирає фінальний системний промпт з фрагментів на основі вектора контексту.

        Args:
            context: Об'єкт ContextVector з повною інформацією про запит.

        Returns:
            Готовий системний промпт у вигляді одного рядка.
        """
        logger.info(f"PromptDirector: Початок збірки промпту для користувача {context.user_id}...")
        prompt_parts: List[str] = []

        # --- Логіка збірки для MVP ---

        # 1. Вибір базової персони
        # Якщо користувач просить технічної допомоги, використовуємо персону "аналітика".
        # В інших випадках — "друга".
        if context.last_message_intent == "technical_help":
            persona_key = "analyst"
        else:
            persona_key = "buddy"
        
        persona_prompt = self.library.get("personas", {}).get(persona_key)
        if persona_prompt:
            prompt_parts.append(persona_prompt)
            logger.debug(f"  [1] Обрано персону: '{persona_key}'")
        else:
            logger.warning(f"  [1] Персона '{persona_key}' не знайдена в бібліотеці.")

        # 2. Додавання деталізації наміру
        intent_prompt = self.library.get("intents", {}).get(context.last_message_intent)
        if intent_prompt:
            prompt_parts.append(intent_prompt)
            logger.debug(f"  [2] Додано намір: '{context.last_message_intent}'")
        else:
            logger.warning(f"  [2] Намір '{context.last_message_intent}' не знайдено в бібліотеці.")

        # 3. Додавання даних профілю користувача (якщо він є)
        if context.user_profile:
            profile_parts = []
            nickname = context.user_profile.get('nickname')
            rank = context.user_profile.get('current_rank')
            
            if nickname:
                profile_parts.append(f"Його нікнейм: {nickname}.")
            if rank:
                profile_parts.append(f"Його поточний ранг: {rank}.")
            
            if profile_parts:
                user_context_prompt = "Це контекст про користувача, до якого ти звертаєшся: " + " ".join(profile_parts)
                prompt_parts.append(user_context_prompt)
                logger.debug(f"  [3] Додано контекст профілю користувача.")

        # 4. Об'єднання всіх частин в один промпт
        final_prompt = "\n\n".join(prompt_parts)
        logger.info(f"PromptDirector: Промпт для {context.user_id} успішно зібрано. Довжина: {len(final_prompt)} символів.")
        
        return final_prompt

# Створюємо єдиний екземпляр директора, який буде використовуватися у всьому застосунку.
# Він автоматично підхопить бібліотеку, завантажену в PROMPT_LIBRARY.
prompt_director = PromptDirector(PROMPT_LIBRARY)
