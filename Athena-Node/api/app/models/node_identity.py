from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NodeIdentity(Base):
    __tablename__ = "node_identities"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_node_identities_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    reported_name: Mapped[str] = mapped_column(String(100), nullable=False)
