"""Sequence policy resolved exclusively from an estimate batch snapshot."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EstimateBatch, KtpEstimateSession
from app.services.floor_structure_service import (
    LOCKED_WBS_SEQUENCE_SCHEMA_V1,
    FloorStructureContractError,
    build_stage_instances,
    validate_building_params,
)


@dataclass(frozen=True)
class SequencePolicy:
    mode: str
    schema: dict[str, Any] | None
    source: str

    @property
    def locked(self) -> bool:
        return self.mode == "locked"


def sequence_policy_from_snapshot(snapshot: Any) -> SequencePolicy:
    if not isinstance(snapshot, Mapping):
        return SequencePolicy(
            mode="editable",
            schema=None,
            source="legacy_taxonomy_snapshot",
        )
    variant = snapshot.get("variant")
    if not isinstance(variant, Mapping):
        return SequencePolicy(
            mode="editable",
            schema=None,
            source="legacy_taxonomy_snapshot",
        )
    schema = variant.get("wbs_sequence_schema")
    if schema is None:
        return SequencePolicy(
            mode="editable",
            schema=None,
            source="legacy_taxonomy_snapshot",
        )
    if not isinstance(schema, Mapping):
        raise FloorStructureContractError(
            "unsupported_wbs_sequence_schema",
            "wbs_sequence_schema должен быть объектом.",
        )
    version = str(schema.get("schema_version") or "")
    if version != LOCKED_WBS_SEQUENCE_SCHEMA_V1:
        raise FloorStructureContractError(
            "unsupported_wbs_sequence_schema",
            f"Неподдерживаемая версия wbs_sequence_schema: {version or '<empty>'}.",
        )
    if str(schema.get("mode") or "") != "locked":
        raise FloorStructureContractError(
            "invalid_wbs_sequence_mode",
            "Для wbs_sequence_schema версии 1.0.0 поддерживается только mode=locked.",
        )
    floor_assignment = schema.get("floor_assignment")
    if not isinstance(floor_assignment, Mapping) or floor_assignment.get("source") != "building_params":
        raise FloorStructureContractError(
            "invalid_floor_assignment_source",
            "floor_assignment.source должен быть building_params.",
        )
    if floor_assignment.get("classification_mode") != "template_anchor":
        raise FloorStructureContractError(
            "invalid_floor_classification_mode",
            "classification_mode должен быть template_anchor.",
        )
    if not isinstance(schema.get("steps"), list) or not schema.get("steps"):
        raise FloorStructureContractError(
            "wbs_sequence_steps_required",
            "Для locked WBS требуется непустой массив steps.",
        )
    return SequencePolicy(
        mode="locked",
        schema=deepcopy(dict(schema)),
        source="taxonomy_wbs_sequence_schema",
    )


def sequence_policy_from_batch(batch: EstimateBatch | None) -> SequencePolicy:
    snapshot = batch.taxonomy_snapshot if batch is not None else None
    policy = sequence_policy_from_snapshot(snapshot)
    if policy.locked and isinstance(snapshot, Mapping):
        variant = snapshot.get("variant")
        if not isinstance(variant, dict):
            raise FloorStructureContractError(
                "wbs_sequence_schema_required", "В snapshot отсутствует variant."
            )
        params = validate_building_params(
            batch.building_params if batch is not None else None,
            variant,
        )
        build_stage_instances(variant, params)
    return policy


async def load_sequence_policy_for_session(
    db: AsyncSession,
    session: KtpEstimateSession,
) -> SequencePolicy:
    batch = await db.get(EstimateBatch, session.estimate_batch_id)
    return sequence_policy_from_batch(batch)
