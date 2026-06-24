"""User-scoped work-rate overrides for source rows marked ``по факту``.

The JSON repository is used by tests and preview deliveries. Production should
back the same contract with the table from migration 060.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

try:
    from app.services.canonical_json_service import LegacyApplicabilityCanonicalJsonV1
except ModuleNotFoundError:  # standalone delivery scripts
    from services.canonical_json_service import LegacyApplicabilityCanonicalJsonV1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_applicability(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Compatibility wrapper around the frozen V1 normalizer."""
    return LegacyApplicabilityCanonicalJsonV1.normalize(payload)


def canonical_applicability_hash(payload: dict[str, Any] | None) -> str:
    """Return the full legacy V1 SHA-256 without changing released bytes."""
    normalized = LegacyApplicabilityCanonicalJsonV1.dumps(payload)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class UserWorkRateOverride:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    source_rate_id: str = ""
    selected_target_code: str = ""
    unit_code: str = ""
    norm_base_quantity: float = 1.0
    applicability_hash: str = ""
    applicability_json: dict[str, Any] = field(default_factory=dict)
    labor_hours_per_norm: float = 0.0
    input_value: float = 0.0
    input_unit: str = "person_hour"
    shift_duration_hours: float = 8.0
    is_active: bool = True
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def reuse_key(self) -> tuple[str, str, str, str, float, str]:
        return (
            self.user_id,
            self.source_rate_id,
            self.selected_target_code,
            self.unit_code,
            float(self.norm_base_quantity),
            self.applicability_hash,
        )


class UserWorkRateOverrideRepository:
    def __init__(self, path: str | Path | None = None):
        configured = str(os.getenv("USER_WORK_RATE_OVERRIDES_FILE") or "").strip()
        self.path = Path(path or configured or Path(__file__).resolve().parents[1] / "data" / "user_work_rate_overrides.json")
        self._lock = threading.RLock()

    def list(self, *, user_id: str | None = None, active_only: bool = True) -> list[UserWorkRateOverride]:
        with self._lock:
            rows = self._load()
        return [
            row for row in rows
            if (not user_id or row.user_id == str(user_id))
            and (not active_only or row.is_active)
        ]

    def find(
        self,
        *,
        user_id: str,
        source_rate_id: str,
        selected_target_code: str,
        unit_code: str,
        norm_base_quantity: float,
        applicability: dict[str, Any] | None,
    ) -> UserWorkRateOverride | None:
        app_hash = canonical_applicability_hash(applicability)
        key = (
            str(user_id), str(source_rate_id), str(selected_target_code), str(unit_code),
            float(norm_base_quantity), app_hash,
        )
        return next((row for row in self.list(user_id=str(user_id)) if row.reuse_key == key), None)

    def upsert(
        self,
        *,
        user_id: str,
        source_rate_id: str,
        selected_target_code: str,
        unit_code: str,
        norm_base_quantity: float,
        applicability: dict[str, Any] | None,
        input_value: float,
        input_unit: str,
        shift_duration_hours: float = 8.0,
    ) -> UserWorkRateOverride:
        if not user_id or not source_rate_id or not selected_target_code or not unit_code:
            raise ValueError("user_id, source_rate_id, selected_target_code and unit_code are required")
        if input_value <= 0 or norm_base_quantity <= 0 or shift_duration_hours <= 0:
            raise ValueError("rate values must be positive")
        if input_unit not in {"person_hour", "person_shift"}:
            raise ValueError("input_unit must be person_hour or person_shift")
        labor_hours = float(input_value) * (float(shift_duration_hours) if input_unit == "person_shift" else 1.0)
        app = normalize_applicability(applicability)
        app_hash = canonical_applicability_hash(app)
        with self._lock:
            rows = self._load()
            existing = next((row for row in rows if row.reuse_key == (
                str(user_id), str(source_rate_id), str(selected_target_code), str(unit_code),
                float(norm_base_quantity), app_hash,
            )), None)
            if existing:
                existing.labor_hours_per_norm = labor_hours
                existing.input_value = float(input_value)
                existing.input_unit = input_unit
                existing.shift_duration_hours = float(shift_duration_hours)
                existing.applicability_json = app
                existing.is_active = True
                existing.updated_at = _now()
                result = existing
            else:
                result = UserWorkRateOverride(
                    user_id=str(user_id), source_rate_id=str(source_rate_id),
                    selected_target_code=str(selected_target_code), unit_code=str(unit_code),
                    norm_base_quantity=float(norm_base_quantity), applicability_hash=app_hash,
                    applicability_json=app, labor_hours_per_norm=labor_hours,
                    input_value=float(input_value), input_unit=input_unit,
                    shift_duration_hours=float(shift_duration_hours),
                )
                rows.append(result)
            self._save(rows)
            return result

    def deactivate(self, override_id: str, *, user_id: str | None = None) -> bool:
        with self._lock:
            rows = self._load()
            row = next((r for r in rows if r.id == override_id and (not user_id or r.user_id == str(user_id))), None)
            if not row:
                return False
            row.is_active = False
            row.updated_at = _now()
            self._save(rows)
            return True

    def _load(self) -> list[UserWorkRateOverride]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw_rows = payload.get("items", []) if isinstance(payload, dict) else payload
        allowed = set(UserWorkRateOverride.__dataclass_fields__)
        return [UserWorkRateOverride(**{k: v for k, v in row.items() if k in allowed}) for row in raw_rows]

    def _save(self, rows: Iterable[UserWorkRateOverride]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format_version": "1.0.0", "items": [row.as_dict() for row in rows]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
