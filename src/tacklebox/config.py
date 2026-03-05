# Configuration settings
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://tacklebox:tacklebox@localhost/tacklebox"
    HOST: str = "127.0.0.1"
    PORT: int = 8420
    FILE_LOCK_STALENESS_SEC: int = 300
    CONTEXT_SUMMARY_LIMIT: int = 20
    STOP_MAX_BLOCKS: int = 3
    SESSION_TIMEOUT_SEC: int = 14400
    LOG_FILE: str = "~/.local/share/tacklebox/server.log"
    LOG_LEVEL: str = "INFO"
    LOG_PROMPTS: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8420"]
    API_KEY: str = ""
    MAX_REQUEST_BODY_BYTES: int = 1_048_576  # 1 MB
    COORDINATION_ACTIVE_WINDOW_SEC: int = 1800  # Exclude sessions idle > 30 min
    COORDINATION_REFRESH_SEC: int = 300  # Re-inject coordination at most every 5 min

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
