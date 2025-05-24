"""
Конфігурація додатку з validation та type safety.
"""

import os
from functools import lru_cache
from typing import Optional
from pydantic import BaseSettings, validator, Field
from pydantic.networks import RedisDsn, PostgresDsn


class Settings(BaseSettings):
    """
    Налаштування додатку з валідацією та типізацією.
    """
    
    # Core Bot Settings
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Telegram Bot API Token")
    ADMIN_CHAT_ID: Optional[int] = Field(None, description="Admin notification chat ID")
    
    # Database
    DATABASE_URL: PostgresDsn = Field(
        default="postgresql+asyncpg://user:pass@localhost/mlbb_db",
        description="PostgreSQL connection URL"
    )
    
    # Redis
    REDIS_URL: RedisDsn = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )
    
    # MLBB API
    MLBB_API_KEY: Optional[str] = Field(None, description="MLBB Official API Key")
    MLBB_API_BASE_URL: str = Field(
        default="https://api.mobilelegends.com/v1",
        description="MLBB API base URL"
    )
    
    # Webhook Settings
    USE_WEBHOOK: bool = Field(default=False, description="Use webhook instead of polling")
    WEBHOOK_URL: Optional[str] = Field(None, description="Webhook URL")
    WEBHOOK_SECRET: Optional[str] = Field(None, description="Webhook secret token")
    WEBHOOK_HOST: str = Field(default="0.0.0.0", description="Webhook host")
    WEBHOOK_PORT: int = Field(default=8080, description="Webhook port")
    
    # Performance Settings
    MAX_CONNECTIONS: int = Field(default=100, description="Max database connections")
    CACHE_TTL: int = Field(default=3600, description="Default cache TTL in seconds")
    RATE_LIMIT_REQUESTS: int = Field(default=30, description="Requests per minute per user")
    
    # Features
    ENABLE_ANALYTICS: bool = Field(default=True, description="Enable analytics")
    ENABLE_CACHING: bool = Field(default=True, description="Enable caching")
    ENABLE_METRICS: bool = Field(default=True, description="Enable metrics collection")
    
    # External Services
    OPENAI_API_KEY: Optional[str] = Field(None, description="OpenAI API key for AI features")
    SENTRY_DSN: Optional[str] = Field(None, description="Sentry DSN for error tracking")
    
    @validator("TELEGRAM_BOT_TOKEN")
    def validate_bot_token(cls, v: str) -> str:
        if not v or len(v.split(":")) != 2:
            raise ValueError("Invalid Telegram bot token format")
        return v
    
    @validator("WEBHOOK_URL")
    def validate_webhook_url(cls, v: Optional[str], values: dict) -> Optional[str]:
        if values.get("USE_WEBHOOK") and not v:
            raise ValueError("WEBHOOK_URL is required when USE_WEBHOOK is True")
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Singleton pattern для налаштувань."""
    return Settings()
