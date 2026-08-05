import re
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator

TELEGRAM_WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


def find_env_file() -> Optional[str]:
    if Path(".env").exists():
        return ".env"

    parent_env = Path("../.env")
    if parent_env.exists():
        return str(parent_env)

    config_dir = Path(__file__).parent

    if (config_dir / ".env").exists():
        return str(config_dir / ".env")

    if (config_dir.parent / ".env").exists():
        return str(config_dir.parent / ".env")

    return None


class Settings(BaseSettings):
    app_env: Literal["development", "test", "staging", "production"] = Field(
        default="development", description="Application environment"
    )
    app_base_url: str = Field(
        default="http://localhost:8000", description="Public backend base URL"
    )
    frontend_base_url: str = Field(
        default="http://localhost:3000", description="Telegram Mini App frontend URL"
    )
    public_v2_enabled: bool = Field(
        default=False, description="Enable public-v2 application behavior"
    )
    telegram_integration_enabled: bool = Field(
        default=False,
        description="Enable Telegram authentication, webhook, and delivery clients",
    )
    invite_only: bool = Field(
        default=True,
        description="Require a claimed beta invite for public-v2 access",
    )
    reminder_worker_enabled: bool = Field(
        default=False,
        description="Permit the standalone durable delivery worker to run",
    )
    inline_staging_worker_enabled: bool = Field(
        default=False,
        description=("Run best-effort delivery polling inside the staging API process"),
    )
    inline_staging_poll_interval_seconds: float = Field(
        default=15.0,
        ge=5.0,
        le=300.0,
        description="Polling interval for the free staging inline worker",
    )
    message_cleanup_enabled: bool = Field(
        default=False,
        description="Queue processed Telegram messages for best-effort deletion",
    )
    message_cleanup_delay_seconds: int = Field(
        default=3600,
        ge=0,
        le=604800,
        description="Retention delay before Telegram message deletion",
    )
    account_deletion_recent_auth_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Maximum session age allowed for account deletion",
    )
    operational_metadata_retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Retention for completed cleanup and session metadata",
    )
    operational_prune_interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Minimum interval between idempotent retention sweeps",
    )
    ai_agent_enabled: bool = Field(
        default=False,
        description="Enable the bounded natural-language assistant",
    )
    ai_provider: Literal["disabled", "groq"] = Field(
        default="disabled",
        description="Provider used for bounded natural-language intent extraction",
    )
    ai_agent_min_confidence: float = Field(
        default=0.80,
        ge=0.5,
        le=1.0,
        description="Minimum confidence for non-destructive agent execution",
    )
    agent_pending_ttl_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        description="Expiry for clarification and confirmation state",
    )
    max_agent_input_length: int = Field(
        default=4000,
        ge=64,
        le=20000,
        description="Maximum natural-language assistant input length",
    )
    max_text_entry_length: int = Field(
        default=10000,
        ge=64,
        le=50000,
        description="Maximum user-supplied text entry length",
    )
    per_user_requests_per_minute: int = Field(
        default=120,
        ge=10,
        le=5000,
    )
    per_user_daily_text_limit: int = Field(default=250, ge=1, le=10000)
    per_user_daily_ai_limit: int = Field(default=50, ge=1, le=5000)
    per_user_daily_nutrition_limit: int = Field(default=50, ge=1, le=1000)
    per_user_daily_summary_limit: int = Field(default=30, ge=1, le=1000)
    per_user_daily_export_limit: int = Field(default=5, ge=1, le=100)
    per_user_daily_voice_minutes: int = Field(default=30, ge=1, le=1440)
    max_reminders_per_user: int = Field(default=100, ge=1, le=5000)
    max_voice_file_size: int = Field(
        default=20 * 1024 * 1024,
        ge=1024,
        le=100 * 1024 * 1024,
    )
    max_voice_duration_seconds: int = Field(default=600, ge=1, le=3600)
    voice_download_timeout_seconds: float = Field(default=30, ge=1, le=120)
    transcription_timeout_seconds: float = Field(default=90, ge=5, le=300)
    voice_provider_max_attempts: int = Field(default=2, ge=1, le=5)
    internal_monitoring_token: str = Field(
        default="",
        description="Optional bearer token for internal operational metrics",
    )
    sentry_dsn: str = Field(
        default="",
        description="Optional Sentry DSN for privacy-safe exception monitoring",
    )
    worker_heartbeat_interval_seconds: int = Field(default=30, ge=5, le=300)
    worker_heartbeat_stale_seconds: int = Field(default=120, ge=30, le=1800)

    telegram_bot_token: str = Field(
        default="", description="Telegram Bot API token from @BotFather"
    )
    telegram_admin_id: Optional[int] = Field(
        default=None, description="Admin user ID for notifications"
    )
    webhook_url: str = Field(
        default="http://localhost:8000", description="Public URL for Telegram webhook"
    )
    telegram_webhook_secret: str = Field(
        default="",
        min_length=0,
        max_length=256,
        description="Secret validated on every Telegram webhook request",
    )
    telegram_webhook_url: str = Field(
        default="", description="Full production Telegram webhook URL"
    )
    telegram_mini_app_url: str = Field(
        default="", description="Telegram Mini App URL configured in BotFather"
    )
    telegram_auth_max_age_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Maximum accepted Telegram Mini App initData age",
    )
    max_webhook_body_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=10_485_760,
        description="Maximum Telegram webhook request body size",
    )

    groq_api_key: str = Field(default="", description="Groq API key")
    groq_model: str = Field(
        default="openai/gpt-oss-120b",
        description="Groq model used for bounded provider calls",
    )
    groq_fallback_model: str = Field(
        default="openai/gpt-oss-20b",
        description="Fallback Groq model used after a strict generation failure",
    )
    llm_temperature: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Temperature for LLM generation"
    )

    database_url: str = Field(
        default="sqlite:///./data/weekly_agent.db",
        description="Application database URL",
    )
    test_database_url: str = Field(
        default="",
        description="Isolated database URL used only when APP_ENV=test",
    )
    chroma_persist_dir: str = Field(
        default="./data/chroma", description="ChromaDB persistence directory"
    )
    nutrition_provider: Literal["disabled", "reference"] = Field(
        default="reference",
        description="Validated nutrition estimation provider",
    )
    worker_poll_interval_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=300,
        description="Idle polling interval for the durable delivery worker",
    )
    worker_batch_size: int = Field(
        default=25,
        ge=1,
        le=250,
        description="Maximum reminders and digests claimed per worker pass",
    )
    worker_lease_seconds: int = Field(
        default=120,
        ge=30,
        le=3600,
        description="Claim lease used to recover jobs after a worker crash",
    )
    worker_max_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Delivery attempts before a job is dead-lettered",
    )
    worker_base_backoff_seconds: int = Field(
        default=30,
        ge=1,
        le=3600,
        description="Initial exponential retry delay",
    )

    whisper_model: str = Field(
        default="whisper-large-v3-turbo",
        description="Groq transcription model identifier",
    )
    whisper_language: str = Field(
        default="auto",
        description="Language for transcription (auto, en, es, fr, de, etc.)",
    )
    audio_temp_dir: str = Field(
        default="./data/audio_temp", description="Temporary directory for audio files"
    )

    timezone: str = Field(default="UTC", description="Timezone for scheduled tasks")
    daily_reflection_hour: int = Field(
        default=23,
        ge=0,
        le=23,
        description="Hour for daily reflection (24-hour format)",
    )
    daily_reflection_minute: int = Field(
        default=59, ge=0, le=59, description="Minute for daily reflection"
    )
    weekly_summary_day: int = Field(
        default=6,
        ge=0,
        le=6,
        description="Day of week for weekly summary (0=Monday, 6=Sunday)",
    )
    weekly_summary_hour: int = Field(
        default=20, ge=0, le=23, description="Hour for weekly summary"
    )
    weekly_summary_minute: int = Field(
        default=0, ge=0, le=59, description="Minute for weekly summary"
    )
    morning_nudge_hour: int = Field(
        default=9, ge=0, le=23, description="Hour for morning nudge"
    )
    morning_nudge_minute: int = Field(
        default=0, ge=0, le=59, description="Minute for morning nudge"
    )
    nudge_threshold_hours: int = Field(
        default=24, ge=1, description="Hours without log before sending reminder"
    )

    enable_random_reminder: bool = Field(
        default=True, description="Enable random daily logging reminder"
    )
    random_reminder_start_hour: int = Field(
        default=10,
        ge=0,
        le=23,
        description="Earliest hour for random reminder (24-hour format)",
    )
    random_reminder_end_hour: int = Field(
        default=20,
        ge=0,
        le=23,
        description="Latest hour for random reminder (24-hour format)",
    )

    evening_summary_hour: int = Field(
        default=23,
        ge=0,
        le=23,
        description="Hour for evening daily summary (24-hour format)",
    )
    evening_summary_minute: int = Field(
        default=0, ge=0, le=59, description="Minute for evening daily summary"
    )

    secret_key: str = Field(
        default="change-me-in-production-use-openssl-rand-hex-32",
        description="Deprecated legacy JWT secret",
    )
    session_signing_secret: str = Field(
        default="", description="Signing secret for short-lived Mini App sessions"
    )
    session_max_age_seconds: int = Field(
        default=900, ge=60, le=86_400, description="Mini App session lifetime"
    )
    session_cookie_name: str = Field(
        default="pr_agent_session",
        description="HTTP-only application session cookie name",
    )
    csrf_cookie_name: str = Field(
        default="pr_agent_csrf", description="CSRF cookie name"
    )
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def effective_session_signing_secret(self) -> str:
        return self.session_signing_secret or self.secret_key

    @property
    def session_cookie_secure(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def active_database_url(self) -> str:
        if self.app_env == "test":
            if not self.test_database_url:
                raise ValueError("TEST_DATABASE_URL is required when APP_ENV=test")
            return self.test_database_url
        return self.database_url

    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="./data/logs/agent.log", description="Log file path")
    json_logs: bool = Field(default=False, description="Output logs in JSON format")

    backup_dir: str = Field(
        default="./data/backups", description="Directory for database backups"
    )
    max_backups: int = Field(
        default=30, ge=1, description="Maximum number of backups to keep"
    )
    backup_hour: int = Field(
        default=3, ge=0, le=23, description="Hour for daily backup (24-hour format)"
    )

    current_week_number: int = Field(
        default=1,
        ge=1,
        description="Legacy-only post counter; unused by public-v2",
    )
    github_username: str = Field(
        default="", description="Legacy-only profile; unused by public-v2"
    )
    linkedin_post_start_year: int = Field(
        default=2026,
        description="Legacy-only start year; unused by public-v2",
    )

    @property
    def linkedin_hashtag_year(self) -> str:
        extra_years = (self.current_week_number - 1) // 52
        return str(self.linkedin_post_start_year + extra_years)

    debug: bool = Field(default=False, description="Enable debug mode")
    disable_ssl_verify: bool = Field(
        default=False, description="Disable SSL verification (development only)"
    )

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if "*" in self.cors_origins_list:
            raise ValueError("CORS_ORIGINS must not contain a wildcard")
        if (
            self.test_database_url
            and self.test_database_url.strip() == self.database_url.strip()
        ):
            raise ValueError(
                "TEST_DATABASE_URL and DATABASE_URL must reference different databases"
            )
        if self.app_env == "test" and not self.test_database_url:
            raise ValueError("TEST_DATABASE_URL is required when APP_ENV=test")

        if self.inline_staging_worker_enabled:
            if self.app_env != "staging":
                raise ValueError(
                    "INLINE_STAGING_WORKER_ENABLED is allowed only in staging"
                )
            if not self.public_v2_enabled:
                raise ValueError(
                    "INLINE_STAGING_WORKER_ENABLED requires PUBLIC_V2_ENABLED"
                )
            if self.reminder_worker_enabled:
                raise ValueError(
                    "Inline staging and dedicated reminder workers are mutually exclusive"
                )

        if not self.telegram_integration_enabled:
            if self.message_cleanup_enabled:
                raise ValueError(
                    "MESSAGE_CLEANUP_ENABLED requires TELEGRAM_INTEGRATION_ENABLED"
                )
            if self.reminder_worker_enabled:
                raise ValueError(
                    "REMINDER_WORKER_ENABLED requires TELEGRAM_INTEGRATION_ENABLED"
                )

        if self.app_env in {"staging", "production"}:
            required = {
                "DATABASE_URL": self.database_url,
                "SESSION_SIGNING_SECRET": self.session_signing_secret,
            }
            if self.telegram_integration_enabled:
                required.update(
                    {
                        "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
                        "TELEGRAM_WEBHOOK_SECRET": self.telegram_webhook_secret,
                        "TELEGRAM_WEBHOOK_URL": self.telegram_webhook_url,
                        "TELEGRAM_MINI_APP_URL": self.telegram_mini_app_url,
                    }
                )
            missing = [
                name
                for name, value in required.items()
                if (
                    not value
                    or any(
                        marker in value.lower()
                        for marker in (
                            "your_",
                            "change-me",
                            "replace_",
                            "example.com",
                        )
                    )
                )
            ]
            if missing:
                raise ValueError(
                    "Missing secure configuration for: " + ", ".join(missing)
                )
            if not self.database_url.startswith(("postgresql://", "postgresql+")):
                raise ValueError("Production DATABASE_URL must use PostgreSQL")
            if len(self.session_signing_secret) < 32:
                raise ValueError(
                    "SESSION_SIGNING_SECRET must contain at least 32 characters"
                )
            if not self.app_base_url.startswith("https://"):
                raise ValueError("Production APP_BASE_URL must use HTTPS")
            if not self.frontend_base_url.startswith("https://"):
                raise ValueError("Production FRONTEND_BASE_URL must use HTTPS")
            if self.telegram_integration_enabled:
                if not TELEGRAM_WEBHOOK_SECRET_PATTERN.fullmatch(
                    self.telegram_webhook_secret
                ):
                    raise ValueError(
                        "TELEGRAM_WEBHOOK_SECRET must contain 16-256 characters "
                        "using only letters, digits, underscores, and hyphens"
                    )
                if not self.telegram_webhook_url.startswith("https://"):
                    raise ValueError("Production TELEGRAM_WEBHOOK_URL must use HTTPS")
                if not self.telegram_mini_app_url.startswith("https://"):
                    raise ValueError("Production TELEGRAM_MINI_APP_URL must use HTTPS")
            if self.disable_ssl_verify:
                raise ValueError("DISABLE_SSL_VERIFY is forbidden outside development")
            if self.debug:
                raise ValueError("DEBUG must be false outside development")
            if any("localhost" in origin for origin in self.cors_origins_list):
                raise ValueError("Production CORS_ORIGINS must not include localhost")
            if self.ai_agent_enabled and (
                self.ai_provider == "disabled" or not self.groq_api_key
            ):
                raise ValueError(
                    "AI_PROVIDER and its credential are required when "
                    "AI_AGENT_ENABLED is true"
                )
            if (
                self.internal_monitoring_token
                and len(self.internal_monitoring_token) < 24
            ):
                raise ValueError(
                    "INTERNAL_MONITORING_TOKEN must contain at least 24 characters"
                )

        return self

    class Config:
        env_file = find_env_file()
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
