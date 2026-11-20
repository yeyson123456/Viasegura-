"""Application settings, loaded from environment variables (documented in .env.example)."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """Runtime configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_env: str = "local"
    api_log_level: str = "INFO"
    # Comma-separated list, e.g. "http://localhost:5173,https://dashboard.example.org"
    api_cors_origins: str = "http://localhost:5173,http://localhost:5174"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "viasegura"
    mongodb_timeout_ms: int = Field(default=3000, ge=100, le=60_000)

    @field_validator("api_log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"must be one of {sorted(_LOG_LEVELS)}")
        return level

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
