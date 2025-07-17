"""
Завантажувач для Бібліотеки Промптів.

Цей модуль сканує директорію prompts/library, завантажує всі .yaml файли
і компілює їх в єдиний словник для легкого доступу в усьому застосунку.
"""
import yaml
import logging
from pathlib import Path
from typing import Any, Dict

# Налаштовуємо логер для цього модуля
logger = logging.getLogger(__name__)

# Визначаємо шлях до директорії з бібліотекою промптів
PROMPTS_LIBRARY_PATH = Path(__file__).parent / "library"

def load_prompt_library() -> Dict[str, Any]:
    """
    Сканує директорію prompts/library, завантажує вміст усіх .yaml файлів
    і повертає їх у вигляді єдиного словника.

    Ключами верхнього рівня у словнику будуть назви файлів без розширення
    (наприклад, 'personas', 'intents').

    Returns:
        Словник з усіма завантаженими фрагментами промптів.
        Повертає порожній словник, якщо директорія не знайдена або порожня.
    """
    if not PROMPTS_LIBRARY_PATH.is_dir():
        logger.error(f"Директорія бібліотеки промптів не знайдена: {PROMPTS_LIBRARY_PATH}")
        return {}

    prompt_library: Dict[str, Any] = {}
    yaml_files = list(PROMPTS_LIBRARY_PATH.glob("*.yaml"))

    if not yaml_files:
        logger.warning(f"У директорії {PROMPTS_LIBRARY_PATH} не знайдено жодного .yaml файлу.")
        return {}

    logger.info(f"Завантаження бібліотеки промптів з {len(yaml_files)} файлів...")

    for file_path in yaml_files:
        # Назва файлу без розширення буде ключем у словнику
        library_key = file_path.stem
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    prompt_library[library_key] = data
                    logger.info(f"  ✅ Файл '{file_path.name}' успішно завантажено в ключ '{library_key}'.")
                else:
                    logger.warning(f"  ⚠️ Файл '{file_path.name}' порожній або містить невалідний YAML.")
        except yaml.YAMLError as e:
            logger.error(f"  ❌ Помилка парсингу YAML у файлі '{file_path.name}': {e}", exc_info=True)
        except Exception as e:
            logger.error(f"  ❌ Не вдалося прочитати або обробити файл '{file_path.name}': {e}", exc_info=True)

    logger.info("✅ Бібліотека промптів успішно завантажена.")
    return prompt_library

# Завантажуємо бібліотеку один раз при імпорті модуля,
# щоб вона була доступна як глобальна змінна.
PROMPT_LIBRARY = load_prompt_library()
