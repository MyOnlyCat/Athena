from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import utc_now


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    host_key_fingerprint: Mapped[str | None] = mapped_column(String(128))
    last_test_status: Mapped[str | None] = mapped_column(String(32))
    last_test_code: Mapped[str | None] = mapped_column(String(64))
    last_test_message: Mapped[str | None] = mapped_column(String(255))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
