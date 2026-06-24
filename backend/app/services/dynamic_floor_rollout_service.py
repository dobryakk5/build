"""Versioned rollout-plan validator for the variant-2.7 feature flag."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROLL_OUT_SCHEMA_VERSION = "dynamic_floor_structure_2_7_rollout@1.0.0"


@dataclass(frozen=True)
class RolloutValidationResult:
    valid: bool
    errors: tuple[str, ...]


class DynamicFloorRolloutPlan:
    def __init__(self, payload: Mapping[str, Any]):
        self.payload = dict(payload)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "DynamicFloorRolloutPlan":
        resolved = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "dynamic_floor_structure_2_7_rollout.json"
        return cls(json.loads(resolved.read_text(encoding="utf-8")))

    def validate(self) -> RolloutValidationResult:
        errors: list[str] = []
        if self.payload.get("schema_version") != ROLL_OUT_SCHEMA_VERSION:
            errors.append("invalid_rollout_schema_version")
        if self.payload.get("initial_mode") != "off":
            errors.append("rollout_must_start_off")
        steps = self.payload.get("steps") or []
        modes = [step.get("mode") for step in steps if isinstance(step, Mapping)]
        if modes[:1] != ["off"] or modes[-1:] != ["on"]:
            errors.append("rollout_sequence_must_be_off_allowlist_on")
        if not any(mode == "allowlist" for mode in modes):
            errors.append("rollout_requires_allowlist_phase")
        rollback = self.payload.get("rollback") or {}
        if rollback.get("mode") != "off" or rollback.get("existing_batches_remain_readable") is not True:
            errors.append("invalid_rollout_rollback_contract")
        return RolloutValidationResult(not errors, tuple(errors))
