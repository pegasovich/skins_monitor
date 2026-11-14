"""Core system settings and runtime configuration."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Immutable application settings with environment variable fallback."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Runtime mode & safety guards
    environment: str = Field(default="development", description="dev/staging/production")
    dry_run: bool = Field(
        default=True,
        description="Dry-run flag. In dry-run, no live outbound notifications are sent.",
    )
    stop_all_outbound: bool = Field(
        default=False,
        description="Global kill-switch: blocks all outgoing notifications immediately.",
    )
    log_level: str = Field(default="INFO", description="Log verbosity level")

    # Financial & Currency
    base_currency: str = Field(default="USD", description="Canonical base currency for comparisons")

    # Storage & Cache
    database_url: str = Field(
        default="sqlite+aiosqlite:///collectibles.db",
        description="Async database connection string",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection for distributed locks and rate limiting",
    )

    # External Provider Credentials
    csfloat_api_key: SecretStr | None = None
    steam_api_key: SecretStr | None = None
    skinport_client_id: str | None = None
    skinport_client_secret: SecretStr | None = None

    # Alert Channels
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    webhook_url: str | None = None
    webhook_hmac_secret: SecretStr | None = None


# Global singleton instance
settings = Settings()
