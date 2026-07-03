"""Personal work-rate catalogue and strict reusable match keys."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserWorkRate


@dataclass(frozen=True, slots=True)
class WorkRateKey:
    taxonomy_code: str
    operation_code: str
    object_scope_code: str | None
    rate_context_code: str | None
    rate_variant_code: str | None
    unit_code: str

    def as_tuple(self) -> tuple[str, str, str | None, str | None, str | None, str]:
        return (
            self.taxonomy_code,
            self.operation_code,
            self.object_scope_code,
            self.rate_context_code,
            self.rate_variant_code,
            self.unit_code,
        )


@dataclass(frozen=True, slots=True)
class UserWorkRateRecord:
    id: str
    user_id: str
    taxonomy_code: str
    operation_code: str
    object_scope_code: str | None
    rate_context_code: str | None
    rate_variant_code: str | None
    unit_code: str
    labor_hours_per_unit: Decimal
    work_name_snapshot: str
    source_estimate_batch_id: str | None = None
    source_estimate_row_id: str | None = None
    taxonomy_version_at_creation: str | None = None
    is_active: bool = True

    @property
    def key(self) -> WorkRateKey:
        return WorkRateKey(
            taxonomy_code=self.taxonomy_code,
            operation_code=self.operation_code,
            object_scope_code=self.object_scope_code,
            rate_context_code=self.rate_context_code,
            rate_variant_code=self.rate_variant_code,
            unit_code=self.unit_code,
        )

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["labor_hours_per_unit"] = str(self.labor_hours_per_unit)
        return result

    @classmethod
    def from_model(cls, row: UserWorkRate) -> "UserWorkRateRecord":
        return cls(
            id=str(row.id),
            user_id=str(row.user_id),
            taxonomy_code=row.taxonomy_code,
            operation_code=row.operation_code,
            object_scope_code=row.object_scope_code,
            rate_context_code=row.rate_context_code,
            rate_variant_code=row.rate_variant_code,
            unit_code=row.unit_code,
            labor_hours_per_unit=Decimal(str(row.labor_hours_per_unit)),
            work_name_snapshot=row.work_name_snapshot,
            source_estimate_batch_id=(
                str(row.source_estimate_batch_id) if row.source_estimate_batch_id else None
            ),
            source_estimate_row_id=str(row.source_estimate_row_id) if row.source_estimate_row_id else None,
            taxonomy_version_at_creation=row.taxonomy_version_at_creation,
            is_active=bool(row.is_active),
        )

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "UserWorkRateRecord":
        return cls(
            id=str(row.get("id") or ""),
            user_id=str(row.get("user_id") or ""),
            taxonomy_code=_required_code(row.get("taxonomy_code"), "taxonomy_code"),
            operation_code=_required_code(row.get("operation_code"), "operation_code"),
            object_scope_code=_optional_code(row.get("object_scope_code")),
            rate_context_code=_optional_code(row.get("rate_context_code")),
            rate_variant_code=_optional_code(row.get("rate_variant_code")),
            unit_code=_required_code(row.get("unit_code"), "unit_code"),
            labor_hours_per_unit=validate_labor_hours(row.get("labor_hours_per_unit")),
            work_name_snapshot=str(row.get("work_name_snapshot") or ""),
            source_estimate_batch_id=_optional_code(row.get("source_estimate_batch_id")),
            source_estimate_row_id=_optional_code(row.get("source_estimate_row_id")),
            taxonomy_version_at_creation=_optional_code(row.get("taxonomy_version_at_creation")),
            is_active=bool(row.get("is_active", True)),
        )


def _optional_code(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_code(value: Any, field_name: str) -> str:
    result = _optional_code(value)
    if result is None:
        raise ValueError(f"{field_name}_required")
    return result


def validate_labor_hours(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("labor_hours_per_unit_invalid") from exc
    if not result.is_finite():
        raise ValueError("labor_hours_per_unit_invalid")
    if result <= 0:
        raise ValueError("labor_hours_per_unit_must_be_positive")
    if result >= Decimal("1000000000000"):
        raise ValueError("labor_hours_per_unit_range_exceeded")
    if abs(result.as_tuple().exponent) > 6:
        raise ValueError("labor_hours_per_unit_scale_exceeded")
    return result.quantize(Decimal("0.000001"))


def build_work_rate_key(
    *,
    taxonomy_code: Any,
    operation_code: Any,
    object_scope_code: Any,
    rate_context_code: Any,
    rate_variant_code: Any = None,
    unit_code: Any = None,
) -> WorkRateKey:
    return WorkRateKey(
        taxonomy_code=_required_code(taxonomy_code, "taxonomy_code"),
        operation_code=_required_code(operation_code, "operation_code"),
        object_scope_code=_optional_code(object_scope_code),
        rate_context_code=_optional_code(rate_context_code),
        rate_variant_code=_optional_code(rate_variant_code),
        unit_code=_required_code(unit_code, "unit_code"),
    )


def coerce_user_rate_records(
    rows: Iterable[UserWorkRateRecord | UserWorkRate | dict[str, Any]] | None,
) -> list[UserWorkRateRecord]:
    result: list[UserWorkRateRecord] = []
    for row in rows or ():
        if isinstance(row, UserWorkRateRecord):
            result.append(row)
        elif isinstance(row, UserWorkRate):
            result.append(UserWorkRateRecord.from_model(row))
        elif isinstance(row, dict):
            result.append(UserWorkRateRecord.from_mapping(row))
        else:
            result.append(
                UserWorkRateRecord.from_mapping(
                    {
                        name: getattr(row, name, None)
                        for name in UserWorkRateRecord.__dataclass_fields__
                    }
                )
            )
    return result


def find_compatible_user_rate(
    *,
    rows: Iterable[UserWorkRateRecord | UserWorkRate | dict[str, Any]] | None,
    user_id: str | None,
    key: WorkRateKey,
) -> UserWorkRateRecord | None:
    if not user_id:
        return None
    owner = str(user_id)
    for row in coerce_user_rate_records(rows):
        if not row.is_active or row.user_id != owner:
            continue
        if row.key == key:
            return row
    return None


class UserWorkRateRepository:
    async def list_records(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        active_only: bool = True,
    ) -> list[UserWorkRateRecord]:
        stmt = select(UserWorkRate).where(UserWorkRate.user_id == str(user_id))
        if active_only:
            stmt = stmt.where(UserWorkRate.is_active.is_(True))
        stmt = stmt.order_by(UserWorkRate.updated_at.desc(), UserWorkRate.id)
        rows = list(await db.scalars(stmt))
        return [UserWorkRateRecord.from_model(row) for row in rows]

    async def get_owned(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        rate_id: str,
    ) -> UserWorkRate | None:
        return await db.scalar(
            select(UserWorkRate).where(
                UserWorkRate.id == str(rate_id),
                UserWorkRate.user_id == str(user_id),
            )
        )

    async def upsert(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        key: WorkRateKey,
        labor_hours_per_unit: Decimal,
        work_name_snapshot: str,
        source_estimate_batch_id: str | None,
        source_estimate_row_id: str | None,
        taxonomy_version_at_creation: str | None,
    ) -> UserWorkRateRecord:
        values = {
            "user_id": str(user_id),
            "taxonomy_code": key.taxonomy_code,
            "operation_code": key.operation_code,
            "object_scope_code": key.object_scope_code,
            "rate_context_code": key.rate_context_code,
            "rate_variant_code": key.rate_variant_code,
            "unit_code": key.unit_code,
            "labor_hours_per_unit": labor_hours_per_unit,
            "work_name_snapshot": str(work_name_snapshot or key.taxonomy_code),
            "source_estimate_batch_id": source_estimate_batch_id,
            "source_estimate_row_id": source_estimate_row_id,
            "taxonomy_version_at_creation": taxonomy_version_at_creation,
            "is_active": True,
        }
        stmt = pg_insert(UserWorkRate).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                UserWorkRate.user_id,
                UserWorkRate.taxonomy_code,
                UserWorkRate.operation_code,
                UserWorkRate.object_scope_code,
                UserWorkRate.rate_context_code,
                UserWorkRate.rate_variant_code,
                UserWorkRate.unit_code,
            ],
            set_={
                "labor_hours_per_unit": stmt.excluded.labor_hours_per_unit,
                "work_name_snapshot": stmt.excluded.work_name_snapshot,
                "source_estimate_batch_id": stmt.excluded.source_estimate_batch_id,
                "source_estimate_row_id": stmt.excluded.source_estimate_row_id,
                "taxonomy_version_at_creation": stmt.excluded.taxonomy_version_at_creation,
                "is_active": True,
                "updated_at": func.now(),
            },
        ).returning(UserWorkRate)
        row = await db.scalar(stmt)
        if row is None:
            raise RuntimeError("user_work_rate_upsert_failed")
        return UserWorkRateRecord.from_model(row)

    async def update_value(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        rate_id: str,
        labor_hours_per_unit: Decimal,
        work_name_snapshot: str | None = None,
    ) -> UserWorkRateRecord | None:
        row = await self.get_owned(db, user_id=user_id, rate_id=rate_id)
        if row is None:
            return None
        row.labor_hours_per_unit = labor_hours_per_unit
        if work_name_snapshot is not None:
            row.work_name_snapshot = work_name_snapshot
        await db.flush()
        return UserWorkRateRecord.from_model(row)

    async def deactivate(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        rate_id: str,
    ) -> bool:
        row = await self.get_owned(db, user_id=user_id, rate_id=rate_id)
        if row is None:
            return False
        row.is_active = False
        await db.flush()
        return True
