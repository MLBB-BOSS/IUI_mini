"""
main.py
Революційна асинхронна платформа Telegram-бота для MLBB-спільноти.
Архітектура: Microservices + Event-Driven + Cache-First
Python 3.11+ | aiogram 3.19+ | Redis | PostgreSQL
"""

import asyncio
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from typing import Any, Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Message, ErrorEvent
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import redis.asyncio as redis

from config.settings import Settings
from handlers import register_all_handlers
from middleware import register_all_middleware
from services.database import DatabaseManager
from services.cache import CacheManager
from services.analytics import AnalyticsService
from services.mlbb_api import MLBBApiService
from utils.logging_config import setup_logging
from utils.metrics import MetricsCollector

# --- Налаштування логування світового класу ---
logger = setup_logging(__name__)

# --- Глобальні стани FSM для MLBB функцій ---
class MLBBStates(StatesGroup):
    waiting_for_player_id = State()
    waiting_for_match_analysis = State()
    waiting_for_team_formation = State()
    waiting_for_tournament_registration = State()

# --- Конфігурація ---
settings = Settings()

class MLBBBot:
    """
    Основний клас бота з enterprise-рівнем архітектури.
    Implements: Dependency Injection, Circuit Breaker, Rate Limiting, Health Checks
    """
    
    def __init__(self) -> None:
        """Ініціалізація всіх компонентів системи."""
        self.settings = settings
        self.bot: Optional[Bot] = None
        self.dp: Optional[Dispatcher] = None
        self.storage: Optional[RedisStorage] = None
        self.db_manager: Optional[DatabaseManager] = None
        self.cache_manager: Optional[CacheManager] = None
        self.analytics: Optional[AnalyticsService] = None
        self.mlbb_api: Optional[MLBBApiService] = None
        self.metrics: Optional[MetricsCollector] = None
        self._shutdown_event = asyncio.Event()
        
    async def initialize_services(self) -> None:
        """Ініціалізація всіх сервісів з graceful error handling."""
        try:
            # Redis для FSM та кешування
            redis_client = redis.Redis.from_url(
                self.settings.REDIS_URL,
                encoding="utf8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30
            )
            
            self.storage = RedisStorage(redis_client)
            self.cache_manager = CacheManager(redis_client)
            
            # Database
            self.db_manager = DatabaseManager(self.settings.DATABASE_URL)
            await self.db_manager.initialize()
            
            # Analytics & Metrics
            self.analytics = AnalyticsService(self.db_manager)
            self.metrics = MetricsCollector()
            
            # MLBB API Service
            self.mlbb_api = MLBBApiService(
                api_key=self.settings.MLBB_API_KEY,
                cache_manager=self.cache_manager
            )
            
            # Bot initialization
            self.bot = Bot(
                token=self.settings.TELEGRAM_BOT_TOKEN,
                default=DefaultBotProperties(
                    parse_mode=ParseMode.HTML,
                    link_preview_is_disabled=True,
                    protect_content=False
                )
            )
            
            self.dp = Dispatcher(storage=self.storage)
            
            # Реєстрація middleware та handlers
            await register_all_middleware(self.dp, self)
            await register_all_handlers(self.dp, self)
            
            logger.info("🚀 Всі сервіси успішно ініціалізовані")
            
        except Exception as exc:
            logger.critical(
                f"❌ Критична помилка ініціалізації: {exc}",
                exc_info=True,
                extra={"service": "initialization", "error_type": type(exc).__name__}
            )
            await self.cleanup()
            raise

    async def setup_error_handlers(self) -> None:
        """Налаштування розширених обробників помилок."""
        
        @self.dp.error()
        async def global_error_handler(event: ErrorEvent) -> None:
            """
            Глобальний обробник помилок enterprise-рівня.
            Features: Error categorization, auto-recovery, admin notifications
            """
            exception = event.exception
            update = event.update
            
            # Категоризація помилок
            error_context = {
                "error_type": type(exception).__name__,
                "user_id": getattr(update.message, "from_user", {}).get("id") if update.message else None,
                "chat_id": getattr(update.message, "chat", {}).get("id") if update.message else None,
                "update_type": type(update).__name__,
                "timestamp": asyncio.get_event_loop().time()
            }
            
            # Metrics collection
            await self.metrics.increment_error_counter(error_context["error_type"])
            
            # Логування з контекстом
            logger.error(
                f"🔥 Bot Error: {exception}",
                exc_info=True,
                extra=error_context
            )
            
            # Analytics tracking
            await self.analytics.track_error(error_context)
            
            # Auto-recovery для деяких типів помилок
            if self._is_recoverable_error(exception):
                logger.info(f"🔄 Спроба автовідновлення для {type(exception).__name__}")
                await self._attempt_recovery(exception, update)
            
            # Критичні помилки - сповіщення адміністратора
            if self._is_critical_error(exception):
                await self._notify_admin(exception, error_context)

    def _is_recoverable_error(self, exception: Exception) -> bool:
        """Визначає, чи можна автоматично відновитися від помилки."""
        recoverable_errors = (
            ConnectionError,
            TimeoutError,
            redis.ConnectionError
        )
        return isinstance(exception, recoverable_errors)
    
    def _is_critical_error(self, exception: Exception) -> bool:
        """Визначає критичні помилки, що потребують негайного втручання."""
        critical_errors = (
            MemoryError,
            SystemError,
            KeyboardInterrupt
        )
        return isinstance(exception, critical_errors)
    
    async def _attempt_recovery(self, exception: Exception, update: Any) -> None:
        """Спроба автоматичного відновлення."""
        # Implementation for auto-recovery logic
        pass
    
    async def _notify_admin(self, exception: Exception, context: dict) -> None:
        """Сповіщення адміністратора про критичні помилки."""
        if self.settings.ADMIN_CHAT_ID and self.bot:
            try:
                await self.bot.send_message(
                    chat_id=self.settings.ADMIN_CHAT_ID,
                    text=f"🚨 <b>КРИТИЧНА ПОМИЛКА</b>\n\n"
                         f"<code>{type(exception).__name__}: {exception}</code>\n\n"
                         f"📊 Контекст: <pre>{context}</pre>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as notify_error:
                logger.error(f"Помилка сповіщення адміністратора: {notify_error}")

    async def setup_signal_handlers(self) -> None:
        """Налаштування обробників сигналів для graceful shutdown."""
        def signal_handler(signum: int, frame: Any) -> None:
            logger.info(f"📡 Отримано сигнал {signum}, ініціація graceful shutdown...")
            self._shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def health_check(self) -> dict[str, Any]:
        """Health check для всіх сервісів."""
        health_status = {
            "bot": False,
            "database": False,
            "cache": False,
            "mlbb_api": False,
            "timestamp": asyncio.get_event_loop().time()
        }
        
        try:
            # Bot health
            if self.bot:
                me = await self.bot.get_me()
                health_status["bot"] = bool(me.id)
            
            # Database health
            if self.db_manager:
                health_status["database"] = await self.db_manager.health_check()
            
            # Cache health
            if self.cache_manager:
                health_status["cache"] = await self.cache_manager.health_check()
            
            # MLBB API health
            if self.mlbb_api:
                health_status["mlbb_api"] = await self.mlbb_api.health_check()
                
        except Exception as exc:
            logger.warning(f"Health check помилка: {exc}")
        
        return health_status

    async def start_polling(self) -> None:
        """Запуск бота в polling режимі з мониторингом."""
        logger.info("🎮 Запуск MLBB Bot у polling режимі...")
        
        try:
            await self.setup_error_handlers()
            await self.setup_signal_handlers()
            
            # Health check task
            async def periodic_health_check():
                while not self._shutdown_event.is_set():
                    health = await self.health_check()
                    await self.metrics.record_health_status(health)
                    await asyncio.sleep(30)  # Check every 30 seconds
            
            health_task = asyncio.create_task(periodic_health_check())
            
            # Start polling
            polling_task = asyncio.create_task(
                self.dp.start_polling(
                    self.bot,
                    allowed_updates=self.dp.resolve_used_update_types(),
                    drop_pending_updates=True
                )
            )
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
            # Graceful shutdown
            logger.info("🛑 Зупинка сервісів...")
            health_task.cancel()
            polling_task.cancel()
            
            try:
                await asyncio.gather(health_task, polling_task, return_exceptions=True)
            except Exception:
                pass
                
        except Exception as exc:
            logger.critical(f"💥 Фатальна помилка polling: {exc}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def start_webhook(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Запуск бота в webhook режимі для production."""
        logger.info(f"🌐 Запуск MLBB Bot у webhook режимі на {host}:{port}")
        
        try:
            await self.setup_error_handlers()
            
            # Webhook setup
            webhook_requests_handler = SimpleRequestHandler(
                dispatcher=self.dp,
                bot=self.bot,
                secret_token=self.settings.WEBHOOK_SECRET
            )
            webhook_requests_handler.register(app := web.Application(), path="/webhook")
            
            # Health check endpoint
            async def health_endpoint(request: web.Request) -> web.Response:
                health = await self.health_check()
                status = 200 if all(health.values()) else 503
                return web.json_response(health, status=status)
            
            app.router.add_get("/health", health_endpoint)
            
            # Metrics endpoint
            async def metrics_endpoint(request: web.Request) -> web.Response:
                metrics_data = await self.metrics.get_all_metrics()
                return web.json_response(metrics_data)
            
            app.router.add_get("/metrics", metrics_endpoint)
            
            setup_application(app, self.dp, bot=self.bot)
            
            # Set webhook
            await self.bot.set_webhook(
                url=f"{self.settings.WEBHOOK_URL}/webhook",
                secret_token=self.settings.WEBHOOK_SECRET,
                allowed_updates=self.dp.resolve_used_update_types(),
                drop_pending_updates=True
            )
            
            # Start server
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            
            logger.info(f"✅ Webhook сервер запущено на http://{host}:{port}")
            
            # Keep running
            await self._shutdown_event.wait()
            
        except Exception as exc:
            logger.critical(f"💥 Фатальна помилка webhook: {exc}", exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """Graceful cleanup всіх ресурсів."""
        logger.info("🧹 Cleanup ресурсів...")
        
        cleanup_tasks = []
        
        if self.bot:
            cleanup_tasks.append(self.bot.session.close())
        
        if self.db_manager:
            cleanup_tasks.append(self.db_manager.close())
        
        if self.cache_manager:
            cleanup_tasks.append(self.cache_manager.close())
        
        if self.storage:
            cleanup_tasks.append(self.storage.close())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        logger.info("✅ Cleanup завершено")

# --- Entrypoint ---
async def main() -> None:
    """
    Головна точка входу з повною обробкою життєвого циклу додатку.
    """
    bot_instance = MLBBBot()
    
    try:
        await bot_instance.initialize_services()
        
        # Production або development режим
        if bot_instance.settings.USE_WEBHOOK:
            await bot_instance.start_webhook(
                host=bot_instance.settings.WEBHOOK_HOST,
                port=bot_instance.settings.WEBHOOK_PORT
            )
        else:
            await bot_instance.start_polling()
            
    except KeyboardInterrupt:
        logger.info("👋 Бот зупинено користувачем")
    except Exception as exc:
        logger.critical(f"💀 Необроблена помилка: {exc}", exc_info=True)
        sys.exit(1)
    finally:
        await bot_instance.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔚 Програма завершена")
