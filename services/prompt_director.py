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

    def _select_persona(self, intent: Intent) -> str:
        """Обирає спеціалізовану персону на основі наміру."""
        if intent in ["technical_help"]: # Видаляємо ambiguous_request звідси
            return "analyst"
        return "buddy"

    def _select_format_instruction(self, intent: Intent) -> str | None:
        """Обирає інструкцію форматування на основі наміру."""
        formats = self.library.get("formats", {})
        # Для ambiguous_request формат вже вбудований у сам промпт
        if intent in ["emotional_support", "celebration", "casual_chat"]:
            return formats.get("ultra_brief")
        if intent == "technical_help":
            return formats.get("detailed")
        return None

    def build_prompt(self, context: ContextVector) -> str:
        """
        Збирає фінальний системний промпт з фрагментів на основі вектора контексту.
        """
        logger.info(f"PromptDirector: Початок збірки промпту для користувача {context.user_id}...")
        prompt_parts: List[str] = []

        # 1. БАЗОВИЙ ШАР: Завжди додаємо основний стиль
        base_persona_prompt = self.library.get("base_persona", {}).get("base_persona")
        if base_persona_prompt:
            prompt_parts.append(base_persona_prompt)
            logger.debug("  [1] Застосовано базовий шар: 'base_persona'")
        else:
            logger.warning("  [1] Увага: 'base_persona' не знайдено в бібліотеці!")

        # ❗️ ПРІОРИТЕТНИЙ РЕЖИМ ДЛЯ НЕОДНОЗНАЧНИХ ЗАПИТІВ
        if context.last_message_intent == "ambiguous_request":
            logger.info("  [!] Активовано пріоритетний режим: 'ambiguous_request'")
            ambiguous_prompt = self.library.get("intents", {}).get("ambiguous_request")
            if ambiguous_prompt:
                prompt_parts.append(ambiguous_prompt)
            else:
                logger.error("  [!] Не знайдено промпт для 'ambiguous_request'!")
            
            final_prompt = "\n\n".join(prompt_parts)
            logger.info(f"PromptDirector: Промпт для {context.user_id} зібрано в пріоритетному режимі.")
            return final_prompt

        # --- Стандартний потік для всіх інших намірів ---

        # 2. СПЕЦІАЛІЗОВАНИЙ ШАР: Обираємо функціональну роль
        persona_key = self._select_persona(context.last_message_intent)
        specialist_persona_prompt = self.library.get("personas", {}).get(persona_key)
        if specialist_persona_prompt:
            prompt_parts.append(specialist_persona_prompt)
            logger.debug(f"  [2] Застосовано спеціалізований шар: '{persona_key}'")

        # 3. КОНТЕКСТНИЙ ШАР: Додаємо решту деталей
        intent_prompt = self.library.get("intents", {}).get(context.last_message_intent)
        if intent_prompt:
            prompt_parts.append(intent_prompt)
            logger.debug(f"  [3] Додано намір: '{context.last_message_intent}'")

        if context.user_profile:
            profile_parts = []
            nickname = context.user_profile.get('nickname')
            rank = context.user_profile.get('current_rank')
            if nickname: profile_parts.append(f"Його нікнейм: {nickname}.")
            if rank: profile_parts.append(f"Його поточний ранг: {rank}.")
            if profile_parts:
                prompt_parts.append("Це контекст про користувача: " + " ".join(profile_parts))
                logger.debug("  [4] Додано контекст профілю.")

        # 4. ФІНАЛЬНИЙ ШАР: Інструкції по формату
        format_instruction = self._select_format_instruction(context.last_message_intent)
        if format_instruction:
            prompt_parts.append(format_instruction)
            logger.debug(f"  [5] Додано інструкцію по формату для наміру '{context.last_message_intent}'.")

        final_prompt = "\n\n".join(prompt_parts)
        logger.info(f"PromptDirector: Промпт для {context.user_id} успішно зібрано. Довжина: {len(final_prompt)} символів.")
        
        return final_prompt

prompt_director = PromptDirector(PROMPT_LIBRARY)
