from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import to_rfc3339
from app.models.deployment import DeploymentEvent


class EventService:
    def __init__(self, session: AsyncSession, master_client: Any) -> None:
        self.session = session
        self.master_client = master_client

    async def append(
        self,
        task_id: str,
        target_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> DeploymentEvent:
        last = await self.session.scalar(
            select(func.max(DeploymentEvent.sequence)).where(
                DeploymentEvent.task_id == task_id
            )
        )
        event = DeploymentEvent(
            task_id=task_id,
            target_id=target_id,
            sequence=(last or 0) + 1,
            event_type=event_type,
            payload=payload,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def deliver_pending(self, task_id: str) -> int:
        events = list(
            (
                await self.session.scalars(
                    select(DeploymentEvent)
                    .where(
                        DeploymentEvent.task_id == task_id,
                        DeploymentEvent.delivered_at.is_(None),
                    )
                    .order_by(DeploymentEvent.sequence)
                )
            ).all()
        )
        if not events or self.master_client is None:
            return 0
        payload = [
            {
                "sequence": event.sequence,
                "target_id": event.target_id,
                "type": event.event_type,
                "occurred_at": to_rfc3339(event.created_at),
                "payload": event.payload,
            }
            for event in events
        ]
        result = await self.master_client.send_events(task_id, payload)
        acknowledged = int(result.get("acknowledged_sequence", 0))
        now = datetime.now(UTC)
        for event in events:
            if event.sequence <= acknowledged:
                event.delivered_at = now
        await self.session.commit()
        return acknowledged
