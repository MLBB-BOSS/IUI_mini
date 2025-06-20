from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def create_party_lobby_keyboard() -> InlineKeyboardMarkup:
    """
    Створює інлайн-клавіатуру для лобі пошуку паті.
    
    :return: Об'єкт InlineKeyboardMarkup з кнопкою "Приєднатися".
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Приєднатися", callback_data="join_party")
    return builder.as_markup()
