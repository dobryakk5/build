from datetime import datetime
import uuid
from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from .base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id:         Mapped[str]      = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name:       Mapped[str]      = mapped_column(String(255), nullable=False)
    slug:       Mapped[str]      = mapped_column(String(100), unique=True, nullable=False)
    plan:       Mapped[str]      = mapped_column(String(20), default="free", nullable=False)
    logo_url:   Mapped[str|None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))

    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete")
    users:    Mapped[list["User"]]    = relationship(back_populates="organization")
