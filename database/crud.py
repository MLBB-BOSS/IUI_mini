"""
Функції для взаємодії з базою даних (Create, Read, Update, Delete).
"""
from typing import Any, Literal

from sqlalchemy import insert, update, select, delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from database.models import User, UserSettings
from config import ASYNC_DATABASE_URL, logger

engine = create_async_engine(ASYNC_DATABASE_URL)


# --- User CRUD ---

async def add_or_update_user(user_data: dict[str, Any]) -> Literal['success', 'conflict', 'error']:
    # ... (код цієї функції залишається без змін) ...
    """
    Додає або оновлює користувача, перевіряючи унікальність player_id.

    Returns:
        - 'success': Користувача успішно створено або оновлено.
        - 'conflict': Такий player_id вже зареєстрований іншим telegram_id.
        - 'error': Сталася інша помилка.
    """
    # 🧠 Уникаємо передачі рядків у поля datetime!
    for dt_field in ("created_at", "updated_at"):
        if dt_field in user_data:
            # Видаляємо, щоб БД сама проставила значення
            user_data.pop(dt_field)

    async with engine.connect() as conn:
        async with conn.begin():
            telegram_id = user_data.get('telegram_id')
            player_id = user_data.get('player_id')

            try:
                # 1. Перевіряємо, чи існує користувач з таким telegram_id
                user_by_telegram_id = await conn.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )
                existing_user = user_by_telegram_id.first()

                if existing_user:
                    # Користувач з таким telegram_id вже існує - це оновлення
                    stmt = (
                        update(User)
                        .where(User.telegram_id == telegram_id)
                        .values(**user_data)
                    )
                    logger.info(f"Оновлення даних для користувача з Telegram ID: {telegram_id}")
                else:
                    # Новий користувач для цього telegram_id - це створення
                    stmt = insert(User).values(**user_data)
                    logger.info(f"Спроба створення нового користувача з Telegram ID: {telegram_id}")

                await conn.execute(stmt)
                await conn.commit()
                return 'success'

            except IntegrityError as e:
                await conn.rollback() # Відкат транзакції
                # 🧠 Більш надійна перевірка на основі тексту помилки від PostgreSQL.
                # SQLAlchemy може по-різному "загортати" вихідні помилки драйвера.
                error_text = str(e).lower()
                if 'unique constraint' in error_text and ('uq_users_player_id' in error_text or 'users_player_id_key' in error_text):
                    logger.warning(f"Конфлікт: Player ID {player_id} вже зареєстровано іншим користувачем. Спроба від Telegram ID {telegram_id}.")
                    return 'conflict'
                else:
                    logger.error(f"Неочікувана помилка цілісності: {e}", exc_info=True)
                    return 'error'
            except Exception as e:
                await conn.rollback()
                logger.error(f"Загальна помилка в add_or_update_user: {e}", exc_info=True)
                return 'error'


async def get_user_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    # ... (код цієї функції залишається без змін) ...
    async with engine.connect() as conn:
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await conn.execute(stmt)
        user_row = result.first()
        if user_row:
            # Перетворюємо результат у словник
            return dict(user_row._mapping)
    return None

async def delete_user_by_telegram_id(telegram_id: int) -> bool:
    # ... (код цієї функції залишається без змін) ...
    """
    Видаляє користувача з бази даних за його Telegram ID.

    Args:
        telegram_id: Унікальний ідентифікатор користувача в Telegram.

    Returns:
        True, якщо користувача було видалено, інакше False.
    """
    async with engine.connect() as conn:
        async with conn.begin():
            stmt = delete(User).where(User.telegram_id == telegram_id)
            result = await conn.execute(stmt)
            await conn.commit()
            # result.rowcount > 0 означає, що було видалено хоча б один рядок
            if result.rowcount > 0:
                logger.info(f"Користувача з Telegram ID {telegram_id} було успішно видалено.")
                return True
            else:
                logger.warning(f"Спроба видалити несуществуючого користувача з Telegram ID {telegram_id}.")
                return False

# --- UserSettings CRUD ---

async def get_user_settings(telegram_id: int) -> UserSettings:
    """
    Отримує налаштування користувача з БД.
    Якщо користувача немає, повертає об'єкт UserSettings з налаштуваннями за замовчуванням.
    """
    async with engine.connect() as conn:
        stmt = select(UserSettings).where(UserSettings.telegram_id == telegram_id)
        result = await conn.execute(stmt)
        settings_row = result.first()
        if settings_row:
            return UserSettings(**settings_row._mapping)
    # Якщо запис не знайдено, повертаємо дефолтний об'єкт
    return UserSettings(telegram_id=telegram_id)


async def update_user_settings(telegram_id: int, **kwargs) -> bool:
    """
    Оновлює або створює (upsert) налаштування для користувача.
    Приймає іменовані аргументи, що відповідають полям моделі UserSettings.
    """
    if not kwargs:
        logger.warning("update_user_settings викликано без даних для оновлення.")
        return False

    async with engine.connect() as conn:
        try:
            async with conn.begin():
                # Використовуємо специфічний для PostgreSQL INSERT ... ON CONFLICT DO UPDATE
                stmt = pg_insert(UserSettings).values(telegram_id=telegram_id, **kwargs)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['telegram_id'],
                    set_=kwargs
                )
                await conn.execute(stmt)
                await conn.commit()
                logger.info(f"Налаштування для користувача {telegram_id} оновлено: {kwargs}")
                return True
        except Exception as e:
            await conn.rollback()
            logger.error(f"Помилка при оновленні налаштувань для {telegram_id}: {e}", exc_info=True)
            return False

# Застаріла функція, яку можна буде видалити після рефакторингу
async def set_user_mute_status(telegram_id: int, is_muted: bool) -> bool:
    """
    DEPRECATED: Встановлює або знімає статус "м'юту" для користувача.
    Замінено на update_user_settings.
    """
    logger.warning("Викликано застарілу функцію set_user_mute_status. "
                   "Перейдіть на update_user_settings.")
    return await update_user_settings(
        telegram_id,
        mute_chat=is_muted,
        mute_vision=is_muted,
        mute_party=is_muted
    )
