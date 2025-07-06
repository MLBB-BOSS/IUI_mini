"""
Визначення моделей даних SQLAlchemy для бази даних.
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger, Float, DateTime, JSON
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
# 🆕 Використовуємо SYNC_DATABASE_URL для створення таблиць
from config import SYNC_DATABASE_URL

Base = declarative_base()

class User(Base):
    """
    Модель, що представляє зареєстрованого користувача (гравця).
    """
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    nickname = Column(String(100), nullable=False)
    player_id = Column(BigInteger, unique=True, nullable=False) # 🧠 ДОДАНО unique=True
    server_id = Column(Integer, nullable=False)
    current_rank = Column(String(50))
    total_matches = Column(Integer)
    win_rate = Column(Float)
    favorite_heroes = Column(String(255)) # Зберігаємо як рядок, розділений комою
    chat_history = Column(JSON, nullable=True) # 🧠 НОВЕ ПОЛЕ ДЛЯ ІСТОРІЇ ЧАТУ
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, nickname='{self.nickname}')>"

# Якщо запускати цей файл напряму, він створить таблиці в БД
if __name__ == '__main__':
    # 🆕 Використовуємо синхронний двигун для цієї операції
    engine = create_engine(SYNC_DATABASE_URL)
    Base.metadata.create_all(engine)
    print("Таблицю 'users' успішно створено (або вона вже існує).")
