from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    port: int = 8080
    log_level: str = "INFO"
    sentry_dsn: str = ""

    # LINE
    line_channel_secret: str
    line_channel_access_token: str

    # Dify
    dify_api_base_url: str = "https://api.dify.ai/v1"
    dify_api_key: str

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # TTL
    session_ttl_seconds: int = 2_592_000   # 30 days
    event_dedup_ttl_seconds: int = 604_800  # 7 days
    reply_token_ttl_seconds: int = 540      # 9 min (< 10 min safety margin)
    job_ttl_seconds: int = 86_400           # 24 hours

    # Timeouts
    dify_timeout_seconds: float = 30.0
    line_reply_timeout_seconds: float = 15.0
    push_fallback_threshold_seconds: float = 45.0


settings = Settings()
