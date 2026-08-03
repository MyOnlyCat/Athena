from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.audit import AuditLog


@dataclass
class AuditedAction:
    session: AsyncSession
    action: str
    target_type: str
    target_id: str | None
    target_label: str | None
    source_ip: str | None
    actor_id: str | None = None
    actor_username: str | None = None
    success_persisted: bool = False

    def set_actor(self, actor_id: str, actor_username: str) -> None:
        self.actor_id = actor_id
        self.actor_username = actor_username

    def set_target(self, target_id: str | None, target_label: str | None) -> None:
        self.target_id = target_id
        self.target_label = target_label

    def _build_log(self, result: str, error_code: str | None) -> AuditLog:
        return AuditLog(
            actor_id=self.actor_id,
            actor_username=self.actor_username,
            action=self.action,
            target_type=self.target_type,
            target_id=self.target_id,
            target_label=self.target_label,
            result=result,
            source_ip=self.source_ip,
            error_code=error_code,
        )

    async def commit_success(self) -> None:
        self.session.add(self._build_log("success", None))
        await self.session.commit()
        self.success_persisted = True

    async def commit_failure(self, error_code: str) -> None:
        self.session.add(self._build_log("failure", error_code))
        await self.session.commit()


async def commit_with_audit(
    session: AsyncSession,
    audit: AuditedAction | None,
) -> None:
    if audit is None:
        await session.commit()
        return
    if audit.session is not session:
        raise RuntimeError("audited action must use the business transaction session")
    await audit.commit_success()


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def capture(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str | None,
        target_label: str | None,
        source_ip: str | None,
        actor_id: str | None = None,
        actor_username: str | None = None,
    ) -> AsyncIterator[AuditedAction]:
        tracked = AuditedAction(
            session=self.session,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            source_ip=source_ip,
            actor_id=actor_id,
            actor_username=actor_username,
        )
        try:
            yield tracked
        except AppError as exc:
            if not tracked.success_persisted:
                await self.session.rollback()
                await tracked.commit_failure(exc.code)
            raise
        except Exception:
            if not tracked.success_persisted:
                await self.session.rollback()
                await tracked.commit_failure("INTERNAL_ERROR")
            raise
        else:
            if not tracked.success_persisted:
                await tracked.commit_success()

    async def list_page(self, page: int, page_size: int) -> tuple[list[AuditLog], int]:
        total = int(await self.session.scalar(select(func.count()).select_from(AuditLog)) or 0)
        logs = list(
            (
                await self.session.scalars(
                    select(AuditLog)
                    .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return logs, total
