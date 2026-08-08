from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.postgres import (
    DEFAULT_IDLE_TRANSACTION_TIMEOUT_MS,
    DEFAULT_LOCK_TIMEOUT_MS,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    is_safe_postgres_schema_name,
)

_PLACEHOLDER_MARKERS = ("replace-with-", "change-me", "changeme")


def _is_repository_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATHENA_MASTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(default="", repr=False)
    database_schema: str = "public"
    jwt_secret: str = Field(default="", repr=False)
    credential_key: str = Field(default="", repr=False)
    service_name: str = "athena-master-api"
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)
    database_statement_timeout_ms: int = Field(
        default=DEFAULT_STATEMENT_TIMEOUT_MS,
        ge=1,
    )
    database_idle_transaction_timeout_ms: int = Field(
        default=DEFAULT_IDLE_TRANSACTION_TIMEOUT_MS,
        ge=1,
    )
    database_lock_timeout_ms: int = Field(default=DEFAULT_LOCK_TIMEOUT_MS, ge=1)
    access_token_minutes: int = Field(default=30, ge=1)
    bootstrap_username: str = ""
    bootstrap_password: str = Field(default="", repr=False)
    data_dir: Path | None = None

    @field_validator("database_schema")
    @classmethod
    def validate_database_schema(cls, value: str) -> str:
        if not is_safe_postgres_schema_name(value):
            raise ValueError("database_schema 必须是安全的 PostgreSQL 标识符")
        return value

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if self.environment == "production" and any(
            _is_repository_placeholder(value)
            for value in (
                self.database_url,
                self.jwt_secret,
                self.credential_key,
                self.bootstrap_password,
            )
        ):
            raise ValueError("生产环境不得使用仓库中的示例占位配置")
        if self.jwt_secret and len(self.jwt_secret) < 32:
            raise ValueError("JWT 密钥至少需要 32 个字符")
        if self.credential_key and len(self.credential_key) != 44:
            raise ValueError("凭据密钥必须是 44 字符的 Fernet 密钥")
        if self.credential_key:
            try:
                Fernet(self.credential_key.encode("ascii"))
            except (TypeError, ValueError) as error:
                raise ValueError("凭据密钥必须是有效的 Fernet 密钥") from error

        if self.environment == "production":
            required = {
                "JWT 密钥": self.jwt_secret,
                "凭据密钥": self.credential_key,
                "初始化管理员用户名": self.bootstrap_username,
                "初始化管理员密码": self.bootstrap_password,
                "数据目录": self.data_dir,
                "数据库配置（PostgreSQL 数据库地址）": self.database_url,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"生产环境缺少必要配置：{'、'.join(missing)}")
        else:
            if self.data_dir is None:
                self.data_dir = Path("./data")
        if not self.database_url:
            raise ValueError("Master 运行时必须显式配置 PostgreSQL 数据库地址")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("Master 运行时数据库必须使用 postgresql+asyncpg")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
