from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

# Виправляємо шлях імпорту, вказуючи на правильний модуль
from database.profile_db import get_user_profile 

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
        async with session_maker() as session:
            user_profile = await get_user_profile(session, message.from_user.id)
        
        return (user_profile is not None) == self.is_registered
