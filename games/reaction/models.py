"""
Визначення моделі даних SQLAlchemy для гри на реакцію.
"""
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    ForeignKey,
    DateTime,
    Index,
)
from sqlalchemy.sql import func

# Імпортуємо декларативну базу з основного файлу моделей,
# щоб ця таблиця була частиною того ж самого Metadata.
# Це критично важливо для коректної роботи Alembic або Base.metadata.create_all().
from database.models import Base


class ReactionGameScore(Base):
    """
    Модель для зберігання результатів гри на реакцію.
    """
    __tablename__ = 'reaction_game_scores'

    id = Column(Integer, primary_key=True)
    
    # Використовуємо ForeignKey для зв'язку з таблицею users.
    # Це забезпечує цілісність даних: не можна зберегти результат для неіснуючого гравця.
    # ondelete="CASCADE" означає, що при видаленні користувача всі його рекорди будуть видалені.
    user_telegram_id = Column(
        BigInteger, 
        ForeignKey('users.telegram_id', ondelete="CASCADE"), 
        nullable=False,
        index=True  # Індекс для швидкого пошуку результатів конкретного гравця
    )
    
    reaction_time_ms = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Створюємо індекс для колонки з часом реакції.
    # Це значно прискорить запити до таблиці лідерів (ORDER BY).
    __table_args__ = (
        Index('ix_reaction_time_ms', 'reaction_time_ms'),
    )

    def __repr__(self) -> str:
        return (
            f"<ReactionGameScore(user_id={self.user_telegram_id}, "
            f"time_ms={self.reaction_time_ms})>"
        )
