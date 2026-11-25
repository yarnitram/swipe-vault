"""Runtime configuration loaded from environment variables (see ../.env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    app_base_url: str = "http://localhost:2100"
    database_url: str = "postgresql+psycopg://swipevault:swipevault_dev_only@postgres:5432/swipevault"
    redis_url: str = "redis://redis:6379/0"
    rq_queue_name: str = "swipevault"
    session_secret: str = "dev-only-insecure-session-secret-change-me"  # noqa: S105
    session_ttl_hours: int = 12
    session_cookie_secure: bool = False
    asset_storage_path: str = "/data/assets"

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    login_max_attempts: int = 5
    login_window_seconds: int = 300

    # Ingestion / file safety limits (FR-03)
    download_max_bytes: int = 26_214_400
    zip_max_expanded_bytes: int = 104_857_600
    zip_max_entries: int = 200
    # When true the API processes jobs inline instead of queueing to RQ (tests / no-worker mode).
    ingest_inline: bool = False

    # Retrieval limits (Phase 2 crawler — FR-02)
    crawl_delay_seconds: float = 2.0
    crawl_max_pages: int = 30
    crawl_max_depth: int = 2
    crawl_timeout_seconds: float = 30.0
    crawl_max_retries: int = 2
    crawl_max_retry_wait_seconds: float = 15.0

    near_duplicate_threshold: float = Field(default=0.90, ge=0.5, le=1.0)

    # Phase 3 Listmonk draft integration (FR-08 — credentials stay in env, never in DB or API responses)
    listmonk_enabled: bool = False
    listmonk_base_url: str | None = None
    listmonk_api_username: str | None = None
    listmonk_api_token: str | None = None
    listmonk_timeout_seconds: float = 15.0

    ai_provider: str = "none"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def listmonk_configured(self) -> bool:
        return bool(
            self.listmonk_base_url
            and self.listmonk_base_url.strip()
            and self.listmonk_api_username
            and self.listmonk_api_token
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
