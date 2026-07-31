from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HostAsset(Base):
    __tablename__ = "host_assets"

    node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("access_nodes.node_id", ondelete="CASCADE"),
        primary_key=True,
    )
    host_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_test_status: Mapped[str | None] = mapped_column(String(32))
    last_test_code: Mapped[str | None] = mapped_column(String(64))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
