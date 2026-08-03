from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.audit import AuditLogPage, AuditLogResponse
from app.services.audit import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    session: SessionDep,
    _: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditLogPage:
    logs, total = await AuditService(session).list_page(page, page_size)
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        page=page,
        page_size=page_size,
        total=total,
    )
