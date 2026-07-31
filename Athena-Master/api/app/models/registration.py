from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class RegistrationApplication(Base):
    __tablename__ = "registration_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    node_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    reported_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    software_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    request_path: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_timestamp: Mapped[str] = mapped_column(String(20), nullable=False)
    auth_nonce: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class AccessNode(Base):
    __tablename__ = "access_nodes"

    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reported_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    software_version: Mapped[str] = mapped_column(String(64), nullable=False)
    management_status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
    )
    encrypted_token: Mapped[str] = mapped_column(String(512), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
