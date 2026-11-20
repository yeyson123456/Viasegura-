"""Application settings, loaded from environment variables (documented in .env.example)."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """Runtime configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- API ---
    api_env: str = "local"
    api_log_level: str = "INFO"
    # Comma-separated list, e.g. "http://localhost:5173,https://dashboard.example.org"
    api_cors_origins: str = "http://localhost:5173,http://localhost:5174"
    # Required by PATCH /incidents/{id}. Empty disables the endpoint.
    admin_api_key: str = ""

    # --- MongoDB ---
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "viasegura"
    mongodb_timeout_ms: int = Field(default=3000, ge=100, le=60_000)
    # Raw reports are deleted this many days after they are received (TTL index).
    reports_ttl_days: int = Field(default=30, ge=1, le=3650)
    # Load the bundled road segments when the collection is empty.
    seed_segments: bool = True
    # How long start-up waits for the schema before serving (it keeps retrying afterwards).
    startup_schema_wait_s: float = Field(default=5.0, ge=0, le=120)

    # --- Consensus: confirmed when N distinct devices report the same type within R m and T min.
    consensus_min_devices: int = Field(default=3, ge=1, le=50)
    consensus_radius_m: float = Field(default=30.0, gt=0, le=500)
    consensus_window_min: int = Field(default=60, ge=1, le=7 * 24 * 60)
    # Device-side confidence below this is refused.
    min_report_confidence: float = Field(default=0.25, ge=0, le=1)
    # Device timestamps older than this (offline queue) or in the future are refused.
    report_max_age_h: int = Field(default=48, ge=1, le=24 * 30)
    # Incidents are linked to the nearest road segment within this distance.
    segment_match_radius_m: float = Field(default=500, gt=0, le=10_000)

    # --- Server-side re-detection (same ONNX model as the phone) ---
    model_path: str = "../../ml/models/hazards.onnx"
    server_check_min_confidence: float = Field(default=0.15, ge=0, le=1)
    # False: a photo the server cannot confirm is flagged "unconfirmed" but still counts
    # (consensus across devices is the main defence). True: such reports are excluded.
    server_check_rejects: bool = False
    max_image_bytes: int = Field(default=1_500_000, ge=10_000, le=10_000_000)

    # --- Storage: Azure Blob (or Azurite) when a connection string is set, else a local folder.
    azure_storage_connection_string: str = ""
    blob_container: str = "report-images"
    events_queue: str = "risk-events"
    media_dir: str = "media"

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
