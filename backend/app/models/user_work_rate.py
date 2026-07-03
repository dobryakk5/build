from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class UserWorkRate(Base, TimestampMixin):
    """A user-owned labour norm that supplements the global rate catalogue.

    The match key is intentionally small and stable. Project, estimate, floor,
    stage and applicability hashes are audit context only and never participate
    in automatic reuse.
    """

    __tablename__ = "user_work_rates"
    __table_args__ = (
        CheckConstraint(
            "labor_hours_per_unit > 0",
            name="ck_user_work_rates_labor_positive",
        ),
        Index(
            "uq_user_work_rates_match_key",
            "user_id",
            "taxonomy_code",
            "operation_code",
            "object_scope_code",
            "rate_context_code",
            "rate_variant_code",
            "unit_code",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_user_work_rates_user_active", "user_id", "is_active"),
        Index(
            "ix_user_work_rates_lookup",
            "user_id",
            "taxonomy_code",
            "operation_code",
            "unit_code",
        ),
    )

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    taxonomy_code: Mapped[str] = mapped_column(Text, nullable=False)
    operation_code: Mapped[str] = mapped_column(Text, nullable=False)
    object_scope_code: Mapped[str | None] = mapped_column(Text)
    rate_context_code: Mapped[str | None] = mapped_column(Text)
    rate_variant_code: Mapped[str | None] = mapped_column(Text)

    unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    labor_hours_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
    )

    work_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    source_estimate_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("estimate_batches.id", ondelete="SET NULL")
    )
    source_estimate_row_id: Mapped[str | None] = mapped_column(
        ForeignKey("estimates.id", ondelete="SET NULL")
    )
    taxonomy_version_at_creation: Mapped[str | None] = mapped_column(String(128))

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
