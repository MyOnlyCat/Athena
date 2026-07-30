from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    source_ip: str | None
    details: dict[str, Any]
    created_at: datetime

