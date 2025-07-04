from aiogram.filters import BaseFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from .db import get_user_profile

# Припустимо, що у вас є асинхронна сесія для роботи з БД
# async_session_maker = create_async_engine(...)

class ProfileRegistrationFilter(BaseFilter):
    """
    Фільтр для перевірки, чи зареєстрований користувач у системі.
    """
    def __init__(self, is_registered: bool):
        """
        Ініціалізує фільтр.

        Args:
            is_registered: Очікуваний стан реєстрації (True або False).
        """
        self.is_registered = is_registered

    async def __call__(self, message: Message, session_maker: async_sessionmaker) -> bool:
        """
        Виконує перевірку під час обробки події.

        Args:
            message: Об'єкт повідомлення від Telegram.
            session_maker: Фабрика сесій для доступу до бази даних.

        Returns:
            True, якщо стан реєстрації користувача відповідає очікуваному,
            інакше False.
        """
        async with session_maker() as session:
            user_profile = await get_user_profile(session, message.from_user.id)
        
        # Повертаємо True, якщо (профіль існує І ми шукаємо зареєстрованих)
        # АБО (профілю не існує І ми шукаємо незареєстрованих).
        return (user_profile is not None) == self.is_registered
