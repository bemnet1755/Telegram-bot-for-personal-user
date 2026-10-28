"""Application settings loaded from the environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values are validated once at start-up."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(..., description="Bot token from @BotFather")
    allowed_telegram_user_id: int = Field(
        ...,
        description="Only this Telegram user id may interact with the bot",
        ge=1,
    )

    # --- Database ---
    database_url: str = Field(
        ...,
        description="Async DSN, e.g. postgresql+asyncpg://user:pass@host:port/db",
    )

    # --- Display / behaviour ---
    currency: str = Field(default="ETB", description="Display currency code")
    timezone: str = Field(default="Africa/Addis_Ababa", description="User timezone")
    allow_negative_stock: bool = Field(
        default=False,
        description="If true, a sale may exceed available stock (default: blocked)",
    )

    # --- Optional AI (natural-language input). Structured flows work without this. ---
    llm_api_key: Optional[str] = None
    llm_api_base: Optional[str] = None
    llm_model: Optional[str] = None

    @property
    def ai_enabled(self) -> bool:
        """AI assistance is opt-in and only on when credentials are configured."""
        return bool(self.llm_api_key and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance (importable by tests via monkeypatch)."""
    return Settings()
