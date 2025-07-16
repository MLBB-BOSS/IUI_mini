"""
Визначення моделей даних SQLAlchemy для бази даних.
Розширено для збереження детальної статистики та інформації з усіх скріншотів.
"""
from typing import override

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    BigInteger,
    Float,
    String,
    DateTime,
    JSON,
    Boolean,  # ❗️ Додано імпорт Boolean
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from config import SYNC_DATABASE_URL

Base = declarative_base()

class User(Base):
    """
    Модель, що представляє зареєстрованого користувача (гравця).
    Тепер містить детальну статистику профілю, матчів і топ-3 героїв.
    """
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    nickname = Column(String(100), nullable=False)
    player_id = Column(BigInteger, unique=True, nullable=False)
    server_id = Column(Integer, nullable=False)
    current_rank = Column(String(50), nullable=True)

    # Базова статистика
    total_matches = Column(Integer, nullable=True)
    win_rate = Column(Float, nullable=True)

    # Детальні дані з профілю
    likes_received = Column(Integer, nullable=True)
    location = Column(String(100), nullable=True)
    squad_name = Column(String(100), nullable=True)

    # Детальна статистика (Statistics → All Seasons)
    stats_filter_type = Column(String(50), nullable=True)
    mvp_count = Column(Integer, nullable=True)
    legendary_count = Column(Integer, nullable=True)
    maniac_count = Column(Integer, nullable=True)
    double_kill_count = Column(Integer, nullable=True)
    most_kills_in_one_game = Column(Integer, nullable=True)
    longest_win_streak = Column(Integer, nullable=True)
    highest_dmg_per_min = Column(Integer, nullable=True)
    highest_gold_per_min = Column(Integer, nullable=True)
    savage_count = Column(Integer, nullable=True)
    triple_kill_count = Column(Integer, nullable=True)
    mvp_loss_count = Column(Integer, nullable=True)
    most_assists_in_one_game = Column(Integer, nullable=True)
    first_blood_count = Column(Integer, nullable=True)
    highest_dmg_taken_per_min = Column(Integer, nullable=True)
    kda_ratio = Column(Float, nullable=True)
    teamfight_participation_rate = Column(Float, nullable=True)
    avg_gold_per_min = Column(Integer, nullable=True)
    avg_hero_dmg_per_min = Column(Integer, nullable=True)
    avg_deaths_per_match = Column(Float, nullable=True)
    avg_turret_dmg_per_match = Column(Integer, nullable=True)

    # Топ-3 улюблених героїв із базовими метриками
    hero1_name = Column(String(50), nullable=True)
    hero1_matches = Column(Integer, nullable=True)
    hero1_win_rate = Column(Float, nullable=True)
    hero2_name = Column(String(50), nullable=True)
    hero2_matches = Column(Integer, nullable=True)
    hero2_win_rate = Column(Float, nullable=True)
    hero3_name = Column(String(50), nullable=True)
    hero3_matches = Column(Integer, nullable=True)
    hero3_win_rate = Column(Float, nullable=True)

    # Збереження шляхів фотографій для розбіжностей Heroku
    basic_profile_file_id = Column(String(255), nullable=True)
    basic_profile_permanent_url = Column(String(512), nullable=True)
    stats_photo_file_id = Column(String(255), nullable=True)
    stats_photo_permanent_url = Column(String(512), nullable=True)
    heroes_photo_file_id = Column(String(255), nullable=True)
    heroes_photo_permanent_url = Column(String(512), nullable=True)
    avatar_file_id = Column(String(255), nullable=True)
    avatar_permanent_url = Column(String(512), nullable=True)

    # Історія чату для AI-асистента
    chat_history = Column(JSON, nullable=True)

    # ❗️ НОВЕ: Налаштування користувача
    is_muted = Column(Boolean, nullable=False, server_default='false')

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @override
    def __repr__(self) -> str:
        return (
            f"<User(telegram_id={self.telegram_id}, "
            f"nickname='{self.nickname}', player_id={self.player_id})>"
        )

# ❗️ НОВЕ: Імпортуємо моделі з інших модулів, щоб Base.metadata.create_all знав про них.
# Це робить систему модульною: просто додайте сюди імпорт нової моделі,
# і її таблиця буде створена автоматично.
from games.reaction.models import ReactionGameScore


if __name__ == '__main__':
    # При прямому запуску створює/оновлює таблицю в БД
    engine = create_engine(SYNC_DATABASE_URL)
    Base.metadata.create_all(engine)
    print("Таблицю 'users' успішно створено або оновлено відповідно до моделі.")
