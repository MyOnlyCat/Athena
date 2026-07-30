from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utc_now


class HostProbeSetting(Base):
    __tablename__ = "host_probe_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_host_probe_settings_singleton"),
        CheckConstraint(
            "interval_minutes >= 1 AND interval_minutes <= 1440",
            name="ck_host_probe_interval_minutes",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
