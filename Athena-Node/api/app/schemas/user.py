from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.time import UtcDatetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    is_active: bool
    last_login_at: UtcDatetime | None
    created_at: UtcDatetime


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_visible_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("用户名不能为空")
        return cleaned


class UserStatusUpdate(BaseModel):
    is_active: bool


class PasswordReset(BaseModel):
    password: str = Field(min_length=12, max_length=128)
