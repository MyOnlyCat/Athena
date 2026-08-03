from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.time import UtcDatetime


class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_ip: str
    target_directory: str
    command: str
    status: str
    progress: int
    exit_code: int | None
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    master_task_id: str
    artifact_name: str
    artifact_sha256: str
    status: str
    claimed_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
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
    created_at: UtcDatetime
