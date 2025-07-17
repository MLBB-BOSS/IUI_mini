"""
Директор Промптів: "мозок" системи, що конструює системні промпти
на основі контексту.
"""
from typing import Any, Dict, List

from config import logger
from prompts.loader import PROMPT_LIBRARY
from services.context_engine import ContextVector, Intent

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

    def _select_format_instruction(self, intent: Intent) -> str | None:
        """Обирає інструкцію форматування на основі наміру."""
        formats = self.library.get("formats", {})
        if intent in ["emotional_support", "celebration", "casual_chat", "ambiguous_request"]:
            return formats.get("ultra_brief")
        if intent == "technical_help":
            return formats.get("detailed")
        return None

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

        # 1. ❗️ ЗАВЖДИ ВИКОРИСТОВУЄМО ЄДИНУ ПЕРСОНУ
        persona_prompt = self.library.get("personas", {}).get("main_persona")
        if persona_prompt:
            prompt_parts.append(persona_prompt)
            logger.debug("  [1] Обрано єдину персону: 'main_persona'")
        else:
            logger.warning("  [1] Увага: 'main_persona' не знайдено в бібліотеці промптів!")


        # 2. Додавання деталізації наміру
        intent_prompt = self.library.get("intents", {}).get(context.last_message_intent)
        if intent_prompt:
            prompt_parts.append(intent_prompt)
            logger.debug(f"  [2] Додано намір: '{context.last_message_intent}'")

        # 3. Додавання даних профілю та статусу користувача
        if context.user_profile and context.last_message_intent != 'ambiguous_request':
            profile_parts = []
            nickname = context.user_profile.get('nickname')
            rank = context.user_profile.get('current_rank')
            if nickname: profile_parts.append(f"Його нікнейм: {nickname}.")
            if rank: profile_parts.append(f"Його поточний ранг: {rank}.")
            
            if profile_parts:
                prompt_parts.append("Це контекст про користувача: " + " ".join(profile_parts))
                logger.debug("  [3] Додано контекст профілю.")
            
            status_modifier = self.library.get("modifiers", {}).get("user_status", {}).get("is_registered")
            if status_modifier: prompt_parts.append(status_modifier)
        elif context.last_message_intent != 'ambiguous_request':
            status_modifier = self.library.get("modifiers", {}).get("user_status", {}).get("is_new")
            if status_modifier: prompt_parts.append(status_modifier)

        # 4. Додавання модифікатора часу доби
        if context.last_message_intent != 'ambiguous_request':
            time_modifier = self.library.get("modifiers", {}).get("time_of_day", {}).get(context.time_of_day)
            if time_modifier:
                prompt_parts.append(time_modifier)
                logger.debug(f"  [4] Додано модифікатор часу доби: '{context.time_of_day}'")
        
        # 5. Додавання інструкції по формату
        format_instruction = self._select_format_instruction(context.last_message_intent)
        if format_instruction:
            prompt_parts.append(format_instruction)
            logger.debug(f"  [5] Додано ФІНАЛЬНУ інструкцію по формату для наміру '{context.last_message_intent}'.")

        final_prompt = "\n\n".join(prompt_parts)
        logger.info(f"PromptDirector: Промпт для {context.user_id} успішно зібрано. Довжина: {len(final_prompt)} символів.")
        
        return final_prompt

prompt_director = PromptDirector(PROMPT_LIBRARY)
