from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATHENA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./data/athena-node.db"
    jwt_secret: str = Field(default="", min_length=32)
    credential_key: str = ""
    service_name: str = "athena-node-api"
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=0)
    access_token_minutes: int = Field(default=30, ge=1)
    bootstrap_username: str = ""
    bootstrap_password: str = ""

    @field_validator("credential_key")
    @classmethod
    def validate_credential_key(cls, value: str) -> str:
        if value and len(value) != 44:
            raise ValueError("credential key must be a 44-character Fernet key")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
