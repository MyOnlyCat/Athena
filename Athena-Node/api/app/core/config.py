from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.node_token import validate_node_token


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
    max_upload_bytes: int = Field(default=1_073_741_824, ge=1)
    host_probe_interval_minutes: int = Field(default=5, ge=1, le=1440)
    node_id: str = ""
    node_name: str = "Athena Node"
    node_version: str = "0.1.0"
    master_node_url: str = ""
    node_token: str = ""
    data_dir: Path = Path("./data")
    allow_http_artifacts: bool = False
    deploy_concurrency: int = Field(default=4, ge=1, le=32)

    @field_validator("credential_key")
    @classmethod
    def validate_credential_key(cls, value: str) -> str:
        if value and len(value) != 44:
            raise ValueError("credential key must be a 44-character Fernet key")
        return value

    @field_validator("node_token")
    @classmethod
    def validate_configured_node_token(cls, value: str) -> str:
        return validate_node_token(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
