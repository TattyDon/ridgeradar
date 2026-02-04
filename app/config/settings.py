"""Application settings and configuration management."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://ridgeradar:password@localhost:5432/ridgeradar",
        description="Async PostgreSQL connection URL",
    )
    database_url_sync: str = Field(
        default="postgresql://ridgeradar:password@localhost:5432/ridgeradar",
        description="Sync PostgreSQL connection URL (for Alembic)",
    )
    db_pool_size: int = Field(default=10, description="Database connection pool size")
    db_max_overflow: int = Field(default=20, description="Max overflow connections")

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # Betfair API
    betfair_username: str = Field(default="", description="Betfair username")
    betfair_password: str = Field(default="", description="Betfair password")
    betfair_app_key: str = Field(default="", description="Betfair application key")
    betfair_cert_path: str = Field(
        default="", description="Path to Betfair SSL certificate"
    )
    betfair_cert_key_path: str = Field(
        default="", description="Path to Betfair SSL certificate key"
    )

    # Application
    secret_key: str = Field(
        default="change-me-in-production",
        description="Secret key for session signing",
    )
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    # Paths
    config_path: Path = Field(
        default=Path(__file__).parent / "defaults.yaml",
        description="Path to defaults.yaml configuration",
    )

    @property
    def betfair_configured(self) -> bool:
        """Check if Betfair credentials are configured."""
        return bool(
            self.betfair_username and self.betfair_password and self.betfair_app_key
        )

    def load_defaults_config(self) -> dict[str, Any]:
        """Load the defaults.yaml configuration file."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return yaml.safe_load(f) or {}
        return {}


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
