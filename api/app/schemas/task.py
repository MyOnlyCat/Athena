from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_ip: str
    target_directory: str
    command: str
    status: str
    progress: int
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    master_task_id: str
    artifact_name: str
    artifact_sha256: str
    status: str
    claimed_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    targets: list[TargetResponse]


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    target_id: str | None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
