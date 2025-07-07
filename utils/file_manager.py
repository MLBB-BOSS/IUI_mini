# utils/file_manager.py
"""
Менеджер стійкості файлів для роботи з Heroku dyno restarts.
Забезпечує постійне зберігання файлів у Cloudinary та fallback механізми.
"""
import asyncio
import io
from typing import Optional
import aiohttp
import cloudinary
import cloudinary.uploader
from aiohttp.client_exceptions import ClientResponseError

from config import logger

# ✅ ВИДАЛЕНО РУЧНУ КОНФІГУРАЦІЮ ТА ЗАЙВІ ІМПОРТИ.
# Бібліотека cloudinary автоматично знайде змінну оточення CLOUDINARY_URL,
# яку ми завантажили в config.py за допомогою load_dotenv().

class FileResilienceManager:
    """
    Менеджер стійкості файлів для Telegram бота на Heroku.
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        """Асинхронний context manager для HTTP сесії."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закриття HTTP сесії."""
        if self.session and not self.session.closed:
            await self.session.close()

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
            max_size_kb: Максимальний розмір у КБ для додаткової компресії.
            
        Returns:
            Постійний URL оптимізованого зображення або None.
        """
        try:
            public_id = f"mlbb_user_{user_id}_{file_type}_optimized"
            
            upload_params = {
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
                upload_params.update({"quality": "auto:low", "width": 800, "height": 800, "crop": "limit"})
            
            # Використовуємо asyncio.to_thread для запуску синхронної бібліотеки в асинхронному коді
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                image_bytes,
                **upload_params
            )
            
            optimized_url = result.get('secure_url')
            if optimized_url:
                logger.info(f"Зображення {file_type} для user {user_id} збережено: {optimized_url}")
                return optimized_url
            
        except Exception as e:
            logger.exception(f"Помилка оптимізації зображення для user {user_id}: {e}")
        
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
