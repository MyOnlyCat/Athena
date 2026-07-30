from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserPage(BaseModel):
    items: list[UserResponse]
    page: int
    page_size: int
    total: int


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def trim_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("用户名不能为空")
        return cleaned


class UserStatusUpdate(BaseModel):
    is_active: bool


class PasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=128)
