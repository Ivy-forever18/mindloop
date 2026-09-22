from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MINDLOOP_", env_file=".env")

    app_name: str = "MindLoop API"
    database_url: str = "sqlite+aiosqlite:///./mindloop.db"
    timezone: str = "Asia/Shanghai"
    focus_activity_threshold_seconds: int = 20
    focus_cooldown_seconds: int = 300


settings = Settings()
