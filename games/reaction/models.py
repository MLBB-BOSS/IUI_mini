"""
Моделі даних SQLAlchemy для гри на реакцію.
"""
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    ForeignKey,
    DateTime,
    func,
)
from sqlalchemy.orm import relationship

# Імпортуємо Base з центрального файлу моделей,
# щоб ця модель була частиною єдиного каталогу метаданих.
from database.models import Base, User


class ReactionGameScore(Base):
    """
    Модель для зберігання найкращого результату гри на реакцію.
    Зберігає лише один, найкращий запис для кожного гравця.
    """
    __tablename__ = 'reaction_scores'

    id = Column(Integer, primary_key=True)
    # Зв'язок з таблицею users через telegram_id, який є унікальним
    user_id = Column(
        BigInteger,
        ForeignKey('users.telegram_id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True
    )
    best_time = Column(Integer, nullable=False)
    last_played_at = Column(DateTime(timezone=True), server_default=func.now())

    # Зворотний зв'язок для легкого доступу до об'єкта User
    user = relationship("User")

    def __repr__(self):
        return (
            f"<ReactionGameScore(user_id={self.user_id}, best_time={self.best_time})>"
        )
