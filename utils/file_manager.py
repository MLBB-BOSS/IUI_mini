"""
utils/file_manager.py

Менеджер стійкості файлів для роботи з Heroku dyno restarts.
Забезпечує постійне зберігання файлів у Cloudinary та fallback механізми.
"""
import asyncio
from typing import Optional, Dict, Any

import aiohttp
import cloudinary
import cloudinary.uploader
from aiohttp.client_exceptions import ClientResponseError

from config import CLOUDINARY_URL, logger

# Явна ініціалізація Cloudinary з URL
try:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)
    logger.info("Cloudinary конфігурація виконана з CLOUDINARY_URL.")
except Exception as e:
    logger.error(f"Не вдалося сконфігурувати Cloudinary з CLOUDINARY_URL: {e}", exc_info=True)


class FileResilienceManager:
    """
    Менеджер стійкості файлів для Telegram бота на Heroku.
    Здійснює оптимізацію та збереження зображень у Cloudinary
    з детальним логуванням та fallback на стандартний URL.
    """

    async def __aenter__(self) -> "FileResilienceManager":
        """Асинхронний context manager для HTTP сесії."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Нічого не закриваємо, бо не відкривали session."""

    async def optimize_and_store_image(
        self,
        image_bytes: bytes,
        user_id: int,
        file_type: str,
        max_size_kb: int = 500
    ) -> Optional[str]:
        """
        Оптимізує зображення та зберігає у Cloudinary.

        Args:
            image_bytes: Байти зображення.
            user_id: ID користувача.
            file_type: Тип файлу ('profile', 'stats', 'heroes', 'avatar').
            max_size_kb: Максимальний розмір у КБ для компресії.

        Returns:
            Постійний URL оптимізованого зображення або None.
        """
        public_id = f"mlbb_user_{user_id}_{file_type}_optimized"
        upload_params: Dict[str, Any] = {
            "public_id": public_id,
            "folder": "mlbb_profiles",
            "resource_type": "image",
            "format": "webp",
            "quality": "auto:good",
            "fetch_format": "auto",
            "overwrite": True,
            "invalidate": True
        }
        if len(image_bytes) > max_size_kb * 1024:
            upload_params.update({
                "quality": "auto:low",
                "width": 800,
                "height": 800,
                "crop": "limit"
            })

        try:
            logger.debug(
                "Cloudinary upload start",
                extra={
                    "user_id": user_id,
                    "file_type": file_type,
                    "upload_params": upload_params
                }
            )
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                image_bytes,
                **upload_params
            )
            logger.debug(
                "Cloudinary upload result",
                extra={"user_id": user_id, "result": result}
            )

            optimized_url = result.get("secure_url") or result.get("url")
            if optimized_url:
                logger.info(
                    f"Image stored for user {user_id}, type={file_type}: {optimized_url}"
                )
                return optimized_url

            logger.warning(
                f"No URL returned for user {user_id}, type={file_type}",
                extra={"result_keys": list(result.keys())}
            )
        except ClientResponseError as e:
            logger.error(
                f"Cloudinary HTTP error for user {user_id}, type={file_type}: {e}",
                exc_info=True
            )
        except Exception as e:
            logger.exception(
                f"Unexpected error optimizing image for user {user_id}, type={file_type}: {e}"
            )
        return None

    @staticmethod
    def get_enhanced_error_message(user_name: str) -> str:
        """
        Повертає покращене повідомлення про помилку для користувача.
        """
        return (
            f"🔄 **Ой, щось пішло не так, {user_name}!**\n\n"
            "Сталася помилка під час завантаження вашого файлу. Можливо, він був тимчасовим.\n\n"
            "📸 **Будь ласка, надішліть зображення ще раз.**\n\n"
            "🙏 Дякуємо за розуміння!"
        )


file_resilience_manager = FileResilienceManager()
