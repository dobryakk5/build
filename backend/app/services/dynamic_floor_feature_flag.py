from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import settings


DYNAMIC_FLOOR_VARIANT_ID = "residential_construction_kirpichnye_doma"


class FeatureFlagError(RuntimeError):
    def __init__(self, code: str, http_status: int):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def normalize_user_id(value: Any) -> str:
    return str(getattr(value, "id", value))


@dataclass(frozen=True)
class DynamicFloorFeatureConfig:
    mode: str = "off"
    allowlist: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, mode: str | None = None, allowlist_text: str | None = None) -> "DynamicFloorFeatureConfig":
        normalized_mode = (mode if mode is not None else settings.DYNAMIC_FLOOR_STRUCTURE_2_7_MODE).strip().lower()
        if normalized_mode not in {"off", "allowlist", "on"}:
            raise FeatureFlagError("dynamic_floor_structure_2_7_mode_invalid", 500)
        raw = settings.DYNAMIC_FLOOR_STRUCTURE_2_7_ALLOWLIST if allowlist_text is None else allowlist_text
        ids: set[str] = set()
        for token in (raw or "").replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                ids.add(str(UUID(token)))
            except ValueError as exc:
                raise FeatureFlagError("dynamic_floor_structure_2_7_allowlist_invalid", 500) from exc
        return cls(mode=normalized_mode, allowlist=frozenset(ids))


class DynamicFloorFeatureGate:
    def __init__(self, config: DynamicFloorFeatureConfig | None = None):
        self.config = config or DynamicFloorFeatureConfig.parse()

    def ensure_allowed(self, *, project_variant_id: str | None, user_id: Any) -> str | None:
        if project_variant_id != DYNAMIC_FLOOR_VARIANT_ID:
            return normalize_user_id(user_id) if user_id is not None else None
        if self.config.mode == "off":
            raise FeatureFlagError("dynamic_floor_structure_2_7_disabled", 409)
        normalized_user = normalize_user_id(user_id)
        if self.config.mode == "allowlist" and normalized_user not in self.config.allowlist:
            raise FeatureFlagError("dynamic_floor_structure_2_7_not_allowed", 409)
        return normalized_user


def validate_dynamic_floor_settings() -> None:
    DynamicFloorFeatureConfig.parse()
