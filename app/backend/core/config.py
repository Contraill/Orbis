from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "production"
    app_name: str = "Orbis"
    build_id: str = Field(default="local",max_length=80,pattern=r"^[a-zA-Z0-9._-]+$")
    tmdb_api_key: str | None = None
    tmdb_language: str = "tr-TR"
    provider_operation_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        le=300,
    )
    database_url: str = "sqlite:////data/media-app.db"

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
