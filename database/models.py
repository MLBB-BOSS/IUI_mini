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
    Boolean,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from config import SYNC_DATABASE_URL

Base = declarative_base()


class UserSettings(Base):
    """
    Модель для зберігання індивідуальних налаштувань користувача.
    Використовує telegram_id як первинний ключ для роботи з усіма користувачами.
    """
    __tablename__ = 'user_settings'

    telegram_id = Column(BigInteger, primary_key=True)
    mute_vision = Column(Boolean, nullable=False, default=False, server_default='false')
    mute_chat = Column(Boolean, nullable=False, default=False, server_default='false')
    mute_party = Column(Boolean, nullable=False, default=False, server_default='false')
    # Поля для майбутніх налаштувань
    # mute_greetings = Column(Boolean, nullable=False, default=False, server_default='false')

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<UserSettings(telegram_id={self.telegram_id}, "
            f"chat={self.mute_chat}, vision={self.mute_vision}, party={self.mute_party})>"
        )


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

    # ... (решта полів моделі User залишаються без змін) ...

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

    # ❗️ ПОЛЕ is_muted тепер є застарілим, але ми його не видаляємо, щоб не зламати міграцію.
    # Воно буде ігноруватися новою логікою.
    is_muted = Column(Boolean, nullable=False, server_default='false')

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @override
    def __repr__(self) -> str:
        return (
            f"<User(telegram_id={self.telegram_id}, "
            f"nickname='{self.nickname}', player_id={self.player_id})>"
        )

# Імпортуємо моделі з інших модулів, щоб Base.metadata.create_all знав про них.
from games.reaction.models import ReactionGameScore


if __name__ == '__main__':
    # При прямому запуску створює/оновлює таблиці в БД
    engine = create_engine(SYNC_DATABASE_URL)
    Base.metadata.create_all(engine)
    print("Таблиці 'users' та 'user_settings' успішно створено або оновлено.")
