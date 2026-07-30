from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUserDep, SessionDep
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    session: SessionDep,
    _: CurrentUserDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLog]:
    return list(
        (
            await session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
            )
        ).all()
    )

