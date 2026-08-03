from sqlalchemy import select

from app.models.deployment import DeploymentEvent
from app.services.events import EventService


class FakeMaster:
    def __init__(self) -> None:
        self.batches = []

    async def send_events(self, task_id, events):
        self.batches.append((task_id, events))
        return {"acknowledged_sequence": events[-1]["sequence"]}


async def test_events_are_ordered_persisted_and_acknowledged(db_session):
    fake = FakeMaster()
    service = EventService(db_session, fake)
    await service.append("release-1", None, "stage", {"stage": "downloading"})
    await service.append("release-1", "target-1", "stdout", {"data": "hello"})

    acknowledged = await service.deliver_pending("release-1")

    assert acknowledged == 2
    assert [event["sequence"] for event in fake.batches[0][1]] == [1, 2]
    assert all(event["occurred_at"].endswith("Z") for event in fake.batches[0][1])
    events = list(
        await db_session.scalars(select(DeploymentEvent).order_by(DeploymentEvent.sequence))
    )
    assert all(event.delivered_at is not None for event in events)
