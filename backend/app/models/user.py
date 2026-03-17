from datetime import datetime
import uuid
from sqlalchemy import String, Boolean, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import TIMESTAMP
TIMESTAMPTZ = TIMESTAMP(timezone=True)
from .base import Base


class User(Base):
    __tablename__ = "users"

    id:              Mapped[str]      = mapped_column(PGUUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))
    email:           Mapped[str]      = mapped_column(String(255), unique=True, nullable=False)
    name:            Mapped[str]      = mapped_column(String(255), nullable=False)
    password_hash:   Mapped[str]      = mapped_column(String(255), nullable=False)
    avatar_url:      Mapped[str|None]
    is_active:       Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:      Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))
    updated_at:      Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    organization: Mapped["Organization|None"] = relationship(back_populates="users")