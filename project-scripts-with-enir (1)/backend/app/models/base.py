from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import TIMESTAMP
TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at + updated_at для всех таблиц где нужно."""
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=text("NOW()"), onupdate=datetime.utcnow, nullable=False
    )


class SoftDeleteMixin:
    """deleted_at — мягкое удаление."""
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)