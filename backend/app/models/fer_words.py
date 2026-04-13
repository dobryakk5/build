from datetime import datetime

from sqlalchemy import Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import TIMESTAMP

from .base import Base

TIMESTAMPTZ = TIMESTAMP(timezone=True)


class FerWordsEntry(Base):
    __tablename__ = "entries"
    __table_args__ = (
        UniqueConstraint("source_sheet", "source_row_number", name="uq_fer_words_entries_sheet_row"),
        {"schema": "fer_words"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sheet: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fer_code: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_tokens: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    human_hours: Mapped[float | None] = mapped_column(Numeric(12, 3))
    machine_hours: Mapped[float | None] = mapped_column(Numeric(12, 3))
    part_1: Mapped[str | None] = mapped_column(Text)
    part_2: Mapped[str | None] = mapped_column(Text)
    part_3: Mapped[str | None] = mapped_column(Text)
    part_4: Mapped[str | None] = mapped_column(Text)
    part_5: Mapped[str | None] = mapped_column(Text)
    part_6: Mapped[str | None] = mapped_column(Text)
    part_7: Mapped[str | None] = mapped_column(Text)
    part_8: Mapped[str | None] = mapped_column(Text)
    part_9: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=text("NOW()"))
