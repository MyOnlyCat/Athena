from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATHENA_MASTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = ""
    jwt_secret: str = ""
    credential_key: str = ""
    service_name: str = "athena-master-api"
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=0)
    access_token_minutes: int = Field(default=30, ge=1)
    bootstrap_username: str = ""
    bootstrap_password: str = ""
    data_dir: Path | None = None

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        if self.jwt_secret and len(self.jwt_secret) < 32:
            raise ValueError("JWT 密钥至少需要 32 个字符")
        if self.credential_key and len(self.credential_key) != 44:
            raise ValueError("凭据密钥必须是 44 字符的 Fernet 密钥")

        if self.environment == "production":
            required = {
                "JWT 密钥": self.jwt_secret,
                "凭据密钥": self.credential_key,
                "初始化管理员用户名": self.bootstrap_username,
                "初始化管理员密码": self.bootstrap_password,
                "数据目录": self.data_dir,
                "数据库配置": self.database_url,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"生产环境缺少必要配置：{'、'.join(missing)}")
        else:
            if not self.database_url:
                self.database_url = "sqlite+aiosqlite:///./data/athena-master.db"
            if self.data_dir is None:
                self.data_dir = Path("./data")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
