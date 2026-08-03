from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.time import as_utc


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: str | None
    actor_username: str | None
    action: str
    target_type: str
    target_id: str | None
    target_label: str | None
    result: str
    source_ip: str | None
    error_code: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return as_utc(value)


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    page: int
    page_size: int
    total: int
