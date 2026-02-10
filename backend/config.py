from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


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
    telegram_bot_token: str = Field(
        default="",
        description="Telegram Bot API token from @BotFather"
    )
    telegram_admin_id: Optional[int] = Field(
        default=None,
        description="Admin user ID for notifications"
    )
    webhook_url: str = Field(
        default="http://localhost:8000",
        description="Public URL for Telegram webhook"
    )
    
    groq_api_key: str = Field(
        default="",
        description="Groq API key"
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model to use (llama-3.3-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768)"
    )
    llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Temperature for LLM generation"
    )
    
    database_url: str = Field(
        default="sqlite:///./data/weekly_agent.db",
        description="Database URL (sqlite:///path or postgresql://user:pass@host:port/db)"
    )
    chroma_persist_dir: str = Field(
        default="./data/chroma",
        description="ChromaDB persistence directory"
    )
    
    whisper_model: str = Field(
        default="base",
        description="Whisper model size (tiny, base, small, medium, large)"
    )
    whisper_language: str = Field(
        default="auto",
        description="Language for transcription (auto, en, es, fr, de, etc.)"
    )
    audio_temp_dir: str = Field(
        default="./data/audio_temp",
        description="Temporary directory for audio files"
    )
    
    timezone: str = Field(
        default="UTC",
        description="Timezone for scheduled tasks"
    )
    daily_reflection_hour: int = Field(
        default=23,
        ge=0,
        le=23,
        description="Hour for daily reflection (24-hour format)"
    )
    daily_reflection_minute: int = Field(
        default=59,
        ge=0,
        le=59,
        description="Minute for daily reflection"
    )
    weekly_summary_day: int = Field(
        default=6,
        ge=0,
        le=6,
        description="Day of week for weekly summary (0=Monday, 6=Sunday)"
    )
    weekly_summary_hour: int = Field(
        default=20,
        ge=0,
        le=23,
        description="Hour for weekly summary"
    )
    weekly_summary_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute for weekly summary"
    )
    morning_nudge_hour: int = Field(
        default=9,
        ge=0,
        le=23,
        description="Hour for morning nudge"
    )
    morning_nudge_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute for morning nudge"
    )
    nudge_threshold_hours: int = Field(
        default=24,
        ge=1,
        description="Hours without log before sending reminder"
    )
    
    enable_random_reminder: bool = Field(
        default=True,
        description="Enable random daily logging reminder"
    )
    random_reminder_start_hour: int = Field(
        default=10,
        ge=0,
        le=23,
        description="Earliest hour for random reminder (24-hour format)"
    )
    random_reminder_end_hour: int = Field(
        default=20,
        ge=0,
        le=23,
        description="Latest hour for random reminder (24-hour format)"
    )
    
    evening_summary_hour: int = Field(
        default=23,
        ge=0,
        le=23,
        description="Hour for evening daily summary (24-hour format)"
    )
    evening_summary_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Minute for evening daily summary"
    )
    
    secret_key: str = Field(
        default="change-me-in-production-use-openssl-rand-hex-32",
        description="Secret key for JWT tokens"
    )
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins"
    )
    
    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    log_file: str = Field(
        default="./data/logs/agent.log",
        description="Log file path"
    )
    json_logs: bool = Field(
        default=False,
        description="Output logs in JSON format"
    )
    
    backup_dir: str = Field(
        default="./data/backups",
        description="Directory for database backups"
    )
    max_backups: int = Field(
        default=30,
        ge=1,
        description="Maximum number of backups to keep"
    )
    backup_hour: int = Field(
        default=3,
        ge=0,
        le=23,
        description="Hour for daily backup (24-hour format)"
    )
    
    current_week_number: int = Field(
        default=57,
        ge=1,
        description="Current week number for LinkedIn posts (started at Week 1, now Week 57+)"
    )
    github_username: str = Field(
        default="ARPANPATRA111",
        description="GitHub username for project links"
    )
    linkedin_post_start_year: int = Field(
        default=2025,
        description="Year when weekly posts started (for hashtag calculation)"
    )
    
    @property
    def linkedin_hashtag_year(self) -> str:
        extra_years = (self.current_week_number - 1) // 52
        return str(self.linkedin_post_start_year + extra_years)
    
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    disable_ssl_verify: bool = Field(
        default=False,
        description="Disable SSL verification (development only)"
    )
    
    class Config:
        env_file = find_env_file()
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
