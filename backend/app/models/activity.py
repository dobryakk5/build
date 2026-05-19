from datetime import datetime
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TIMESTAMPTZ


class ActivityEvent(Base):
    """Product-level user activity log."""

    __tablename__ = "user_activity_events"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    session_id: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(PGUUID(as_uuid=False))
    path: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ,
        server_default=sa_text("NOW()"),
        nullable=False,
    )

    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])
