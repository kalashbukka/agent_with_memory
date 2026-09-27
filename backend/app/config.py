from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: float = 45.0

    hindsight_api_key: str = ""
    hindsight_base_url: str = "https://api.hindsight.vectorize.io"
    hindsight_bank_id: str = "incident-response-agent"
    hindsight_timeout_seconds: float = 60.0
    # Minimum cross-encoder relevance for a memory from a *different* service
    # to be shown. Same-service memories are always considered relevant.
    hindsight_min_relevance: float = 0.3

    demo_username: str = "admin"
    demo_password: str = "admin123"

    database_path: Path = BACKEND_DIR / "incidents.db"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://frontend-rouge-two-76.vercel.app",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
