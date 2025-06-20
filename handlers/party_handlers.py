"""
Обробники для створення та управління лобі для пошуку паті.
Використовує FSM для покрокового створення лобі.
"""
import html
import logging
import re
from typing import List

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from keyboards.inline_keyboards import (
    create_party_confirmation_keyboard,
    create_role_selection_keyboard,
    create_dynamic_lobby_keyboard
)
from states.party_states import PartyCreation
from config import logger

# Словник для зберігання активних лобі. В ідеалі це має бути база даних (Redis, PostgreSQL).
# Для прототипу словник є прийнятним рішенням.
active_lobbies = {}

# Усі ролі, доступні в грі
ALL_ROLES = ["Танк/Підтримка", "Лісник", "Маг (мід)", "Стрілець (золото)", "Боєць (досвід)"]

party_router = Router()

def get_lobby_message_text(lobby_data: dict) -> str:
    """Форматує текст повідомлення для лобі."""
    leader_name = html.escape(lobby_data['leader_name'])
    
    players_list = []
    role_emoji_map = {
        "Танк/Підтримка": "🛡️", "Лісник": "🌳", "Маг (мід)": "🧙",
        "Стрілець (золото)": "🏹", "Боєць (досвід)": "⚔️"
    }
    
    taken_roles = []
    for player_id, player_info in lobby_data['players'].items():
        role = player_info['role']
        name = html.escape(player_info['name'])
        emoji = role_emoji_map.get(role, "🔹")
        players_list.append(f"• {emoji} <b>{role}:</b> {name}")
        taken_roles.append(role)

    available_roles_list = [f"• {role_emoji_map.get(r, '🔹')} {r}" for r in ALL_ROLES if r not in taken_roles]

    header = f"🔥 <b>Збираємо паті на рейтинг!</b> 🔥\n\n<b>Ініціатор:</b> {leader_name}\n"
    players_section = "<b>Учасники:</b>\n" + "\n".join(players_list)
    
    available_section = ""
    if available_roles_list:
        available_section = "\n\n<b>Вільні ролі:</b>\n" + "\n".join(available_roles_list)
    else:
        available_section = "\n\n✅ <b>Команда зібрана!</b>"

    return f"{header}\n{players_section}{available_section}"


@party_router.message(F.text & F.func(lambda msg: re.search(r'\b(паті|паті|команду|пати)\b', msg.text.lower()) and re.search(r'\b(збираю|го|шукаю)\b', msg.text.lower())))
async def ask_for_party_creation(message: Message, state: FSMContext):
    """
    Перехоплює повідомлення про пошук паті та запускає FSM.
    """
    await state.set_state(PartyCreation.confirm_creation)
    await message.reply(
        "Бачу, ти хочеш зібрати команду. Допомогти тобі?",
        reply_markup=create_party_confirmation_keyboard()
    )

@party_router.callback_query(PartyCreation.confirm_creation, F.data == "party_create_cancel")
async def cancel_party_creation(callback: CallbackQuery, state: FSMContext):
    """Обробляє відмову від створення паті."""
    await state.clear()
    await callback.message.edit_text("Гаразд. Якщо передумаєш - звертайся! 😉")
    await callback.answer()

@party_router.callback_query(PartyCreation.confirm_creation, F.data == "party_create_confirm")
async def prompt_for_role(callback: CallbackQuery, state: FSMContext):
    """
    Після підтвердження, запитує у ініціатора його роль.
    """
    await state.set_state(PartyCreation.select_role)
    await callback.message.edit_text(
        "Чудово! Оберіть свою роль, щоб інші знали, кого ви шукаєте:",
        reply_markup=create_role_selection_keyboard(ALL_ROLES)
    )
    await callback.answer()

@party_router.callback_query(PartyCreation.select_role, F.data.startswith("party_role_select_"))
async def create_party_lobby(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """
    Фінальний крок. Створює лобі, додає ініціатора та публікує повідомлення.
    """
    user = callback.from_user
    selected_role = callback.data.split("party_role_select_")[1]
    
    # Створюємо унікальний ID для лобі на основі ID повідомлення
    lobby_id = str(callback.message.message_id)
    
    # Створюємо структуру даних для лобі
    # **ОСЬ КЛЮЧОВИЙ ФІКС:** ініціатор одразу додається до гравців
    lobby_data = {
        "leader_id": user.id,
        "leader_name": user.first_name,
        "players": {
            user.id: {
                "name": user.first_name,
                "role": selected_role
            }
        },
        "chat_id": callback.message.chat.id
    }
    
    active_lobbies[lobby_id] = lobby_data
    logger.info(f"Створено нове лобі {lobby_id} ініціатором {user.first_name} (ID: {user.id}) з роллю {selected_role}")

    # Генеруємо фінальне повідомлення та клавіатуру
    message_text = get_lobby_message_text(lobby_data)
    keyboard = create_dynamic_lobby_keyboard(lobby_id, user.id, lobby_data)
    
    await callback.message.edit_text(message_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer(f"Ви зайняли роль: {selected_role}")
    await state.clear()

def register_party_handlers(dp: Dispatcher):
    """Реєструє обробники для функціоналу паті."""
    dp.include_router(party_router)
    logger.info("Обробники для створення паті (FSM) успішно зареєстровано.")
