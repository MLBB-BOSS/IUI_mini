import sqlite3
import json
import time
from typing import List, Dict, Any, Optional

from config import logger

DB_PATH = "lobbies.db"

def initialize_database():
    """Створює таблицю для лобі, якщо вона не існує."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lobbies (
                    chat_id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL,
                    leader_id INTEGER NOT NULL,
                    party_size INTEGER NOT NULL,
                    players TEXT NOT NULL,
                    roles_left TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)
            conn.commit()
            logger.info("✅ Базу даних для лобі успішно ініціалізовано.")
    except sqlite3.Error as e:
        logger.critical(f"❌ Критична помилка при ініціалізації бази даних: {e}")
        raise

def add_lobby(chat_id: int, message_id: int, leader_id: int, party_size: int, players: Dict, roles_left: List[str], expires_at: int):
    """Додає нове лобі або оновлює існуюче в базі даних."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO lobbies (chat_id, message_id, leader_id, party_size, players, roles_left, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (chat_id, message_id, leader_id, party_size, json.dumps(players), json.dumps(roles_left), expires_at))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Помилка при додаванні/оновленні лобі для chat_id {chat_id}: {e}")

def get_lobby(chat_id: int) -> Optional[Dict[str, Any]]:
    """Отримує дані лобі з бази даних за ID чату."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lobbies WHERE chat_id = ?", (chat_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "chat_id": row[0], "message_id": row[1], "leader_id": row[2], "party_size": row[3],
                    "players": json.loads(row[4]), "roles_left": json.loads(row[5]), "expires_at": row[6]
                }
            return None
    except sqlite3.Error as e:
        logger.error(f"Помилка при отриманні лобі для chat_id {chat_id}: {e}")
        return None

def remove_lobby(chat_id: int):
    """Видаляє лобі з бази даних."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM lobbies WHERE chat_id = ?", (chat_id,))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Помилка при видаленні лобі для chat_id {chat_id}: {e}")

def get_all_lobbies() -> List[Dict[str, Any]]:
    """Отримує всі активні лобі з бази даних."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lobbies")
            rows = cursor.fetchall()
            lobbies = []
            for row in rows:
                lobbies.append({
                    "chat_id": row[0], "message_id": row[1], "leader_id": row[2], "party_size": row[3],
                    "players": json.loads(row[4]), "roles_left": json.loads(row[5]), "expires_at": row[6]
                })
            return lobbies
    except sqlite3.Error as e:
        logger.error(f"Помилка при отриманні всіх лобі: {e}")
        return []
