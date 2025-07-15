"""
Централізоване сховище текстових повідомлень для гри на реакцію.
Це дозволяє легко змінювати тексти та підтримувати локалізацію,
не торкаючись логіки обробників.
"""
from typing import List, Dict, Any

# === ЗАГАЛЬНІ ПОВІДОМЛЕННЯ ===
MSG_GAME_TITLE = "<b>Гра на реакцію</b>"
MSG_SUBTITLE = "Перевірте свою швидкість!"
MSG_ERROR_NO_MESSAGE = "Помилка: не вдалося отримати повідомлення."
MSG_ERROR_NOT_REGISTERED = "Будь ласка, спочатку зареєструйтесь за допомогою команди /profile"
MSG_PREPARE = "Приготуйся..."
MSG_TOO_EARLY = "Зарано!"
MSG_GAME_OVER = "Гра вже закінчилась або неактивна."

# === ІГРОВИЙ ПРОЦЕС ===
def get_loading_text(loading_bar: str) -> str:
    return (
        f"{MSG_GAME_TITLE}\n\n{loading_bar}\n\n"
        "Щойно кружечок стане зеленим (🟢), тисни на нього!"
    )

MSG_PRESS_NOW = f"{MSG_GAME_TITLE}\n\n🟢\n\nТИСНИ!"
MSG_FALSE_START = "<b>Фальстарт!</b>\n\nВи натиснули занадто рано. Спробуйте ще раз."

# === РЕЗУЛЬТАТИ ТА ТАБЛИЦЯ ЛІДЕРІВ ===
MSG_NEW_TOP_10_ENTRY = "🏆 Ви увірвалися в топ-10!"

def get_personal_best_text(position: int) -> str:
    return f"🚀 Новий особистий рекорд! Ви піднялись на {position} місце!"

def get_result_text(time_ms: int, new_best_text: str, fact: str) -> str:
    return (
        f"<b>Ваш результат: {time_ms} мс</b>\n"
        f"<i>{new_best_text}</i>\n\n"
        f"🧐 <b>Цікавий факт:</b> {fact}"
    )

def get_leaderboard_text(leaderboard_data: List[Dict[str, Any]], user_id: int) -> str:
    if not leaderboard_data:
        return "<b>🏆 Таблиця лідерів порожня.</b>\n\nСтаньте першим!"

    lines = ["<b>🏆 Таблиця лідерів (Топ-10):</b>"]
    for i, record in enumerate(leaderboard_data, 1):
        is_current_user = "👉" if record["telegram_id"] == user_id else "  "
        lines.append(
            f"{is_current_user}{i}. {record['nickname']} - <b>{record['best_time']} мс</b>"
        )
    return "\n".join(lines)

def get_user_time_answer(time_ms: int) -> str:
    return f"Ваш час: {time_ms} мс"
