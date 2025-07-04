from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

# Припускаємо, що у вас є функція для отримання профілю
# Якщо вона називається інакше або знаходиться в іншому місці, змініть імпорт
from .db import get_user_profile 

class ProfileRegistrationFilter(BaseFilter):
    """
    Фільтр для перевірки, чи зареєстрований користувач у системі.
    """
    def __init__(self, is_registered: bool):
        self.is_registered = is_registered

    async def __call__(self, message: Message, session_maker: async_sessionmaker) -> bool:
        """
        Виконує перевірку під час обробки події.
        """
        # Важливо: ваш middleware повинен передавати session_maker у хендлери
        async with session_maker() as session:
            user_profile = await get_user_profile(session, message.from_user.id)
        
        return (user_profile is not None) == self.is_registered
