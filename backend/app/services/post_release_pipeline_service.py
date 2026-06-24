"""Deterministic post-import projections, KTP and GPR reference pipeline.

The service connects stages 4, 5 and 9 for the stage-10 E2E contract.  It reads
only the immutable taxonomy snapshot stored on the batch and the materialized
Estimate rows produced by the confirmed-snapshot worker.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import UUID, uuid5

try:
    from app.services.estimate_batch_revalidation_service import BlockedBatchGuard
    from app.services.estimate_preview_service import SqliteEstimatePreviewStore, _json_dump, _json_load, _iso, utcnow
    from app.services.floor_structure_service import BuildingParams, build_stage_instances
    from app.services.ktp_floor_sequence_service import (
        STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID,
        build_brick_house_floor_dependencies,
        projection_metadata,
    )
    from app.services.quantity_projection_service import enrich_quantity_projections
    from app.services.semantic_options_service import (
        generate_semantic_operation_projections,
        resolve_semantic_options,
    )
except ModuleNotFoundError:
    from services.estimate_batch_revalidation_service import BlockedBatchGuard
    from services.estimate_preview_service import SqliteEstimatePreviewStore, _json_dump, _json_load, _iso, utcnow
    from services.floor_structure_service import BuildingParams, build_stage_instances
    from services.ktp_floor_sequence_service import (
        STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID,
        build_brick_house_floor_dependencies,
        projection_metadata,
    )
    from services.quantity_projection_service import enrich_quantity_projections
    from services.semantic_options_service import (
        generate_semantic_operation_projections,
        resolve_semantic_options,
    )

PIPELINE_NAMESPACE = UUID("bf2f12ec-7669-58c3-b788-c88855a66d20")


def _id(kind: str, batch_id: str, value: str) -> str:
    return str(uuid5(PIPELINE_NAMESPACE, f"{kind}:{batch_id}:{value}"))


@dataclass(frozen=True)
class PostImportPipelineResult:
    batch_id: str
    stage_instance_count: int
    quantity_projection_count: int
    ktp_group_count: int
    ktp_item_count: int
    gantt_task_count: int
    milestone_created: bool

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class PostImportCalculationPipeline:
    def __init__(self, *, store: SqliteEstimatePreviewStore):
        self.store = store
        self.guard = BlockedBatchGuard(store)

    def run(self, batch_id: Any) -> PostImportPipelineResult:
        batch = self.guard.ensure_operation_allowed(batch_id, "recalculate")
        batch_id = str(batch["id"])
        snapshot = _json_load(batch["taxonomy_snapshot"], {})
        variant = snapshot.get("variant") or {}
        session = self.store.connection.execute(
            "SELECT * FROM estimate_preview_sessions WHERE estimate_batch_id=?", (batch_id,)
        ).fetchone()
        if session is None:
            raise ValueError("batch preview session is required")
        building = _json_load(session["building_params"], {})
        params = BuildingParams(
            floors_count=int(building.get("floors_count") or 0),
            has_basement=bool(building.get("has_basement")),
            has_mansard=bool(building.get("has_mansard")),
        )
        stages = build_stage_instances(variant, params)
        options = _json_load(batch["project_structure_options"], {})
        resolve_semantic_options(variant, stages, project_structure_options=options)

        estimates = self.store.connection.execute(
            "SELECT * FROM estimates WHERE estimate_batch_id=? ORDER BY source_row_index, source_row_key",
            (batch_id,),
        ).fetchall()
        stage_lookup = self._stage_lookup(stages)
        evidence: list[dict[str, Any]] = []
        row_objects: list[SimpleNamespace] = []
        estimate_by_source: dict[str, str] = {}

        for row in estimates:
            parsed = _json_load(row["parsed_data"], {})
            classified = _json_load(row["classification_result"], {})
            template = str(classified.get("template_stage_number") or "")
            floor_number = classified.get("floor_number")
            if floor_number is None and template == "2.7.8":
                floor_number = 1
            stage = stage_lookup.get((template, floor_number)) or stage_lookup.get((template, None))
            if stage is None:
                continue
            option_ids = list(stage.get("semantic_stage_option_ids") or [])
            option_id = classified.get("semantic_stage_option_id") or (option_ids[0] if option_ids else None)
            operation_code = (
                classified.get("operation_code")
                or classified.get("selected_operation_code")
                or stage.get("primary_operation_code")
                or self._first_operation(stage)
            )
            if not operation_code:
                continue
            source_key = str(row["source_row_key"])
            estimate_by_source[source_key] = str(row["id"])
            evidence.append({
                "stage_instance_id": stage["stage_instance_id"],
                "semantic_stage_option_id": option_id,
                "operation_code": operation_code,
                "source_row_key": source_key,
                "work_scope_key": row["work_scope_key"],
                "applicability_hash": row["applicability_hash"],
                "applicability_hash_version": row["applicability_hash_version"],
                "applicability_schema_version": row["applicability_schema_version"],
                "quantity": parsed.get("quantity"),
                "unit_code": parsed.get("unit") or parsed.get("unit_code"),
                "quantity_source": "explicit",
                "materialization_source": "matched_to_source_row",
            })
            raw_data = {
                "row_role": "work",
                "work_type_applicable": True,
                "source_row_key": source_key,
                "work_scope_key": row["work_scope_key"],
                "template_stage_number": template,
                "stage_instance_id": stage["stage_instance_id"],
                "stage_number": stage.get("number"),
                "canonical_stage_id": stage.get("canonical_stage_id"),
                "floor_number": stage.get("floor_number"),
                "floor_kind": stage.get("floor_kind"),
                "floor_label": stage.get("floor_label"),
                "floor_component": stage.get("floor_component"),
                "component_role": stage.get("component_role"),
                "operation_code": operation_code,
                "semantic_stage_option_id": option_id,
                "stage_option_source": stage.get("stage_option_source") or "classified_from_row",
                "applicability": _json_load(row["applicability"], {}),
                "applicability_hash": row["applicability_hash"],
                "applicability_hash_version": row["applicability_hash_version"],
                "applicability_schema_version": row["applicability_schema_version"],
                "resolution_status": "resolved",
                "calculation_blocked": False,
            }
            row_objects.append(SimpleNamespace(
                id=row["id"], quantity=parsed.get("quantity"), unit=parsed.get("unit") or parsed.get("unit_code"),
                work_name=row["source_text"], raw_data=raw_data,
            ))

        generate_semantic_operation_projections(variant, stages, evidence=evidence)
        enrich_quantity_projections(row_objects, variant=variant, stage_instances=stages)

        groups = [SimpleNamespace(
            id=_id("ktp-group", batch_id, stage["stage_instance_id"]),
            stage_instance_id=stage["stage_instance_id"],
            template_stage_number=stage.get("template_stage_number"),
            stage_number=stage.get("number"),
            canonical_stage_id=stage.get("canonical_stage_id"),
            floor_number=stage.get("floor_number"),
            floor_kind=stage.get("floor_kind"),
            floor_label=stage.get("floor_label"),
            floor_component=stage.get("floor_component"),
            component_role=stage.get("component_role"),
            sort_order=stage.get("sort_order"),
            title=stage.get("title"),
        ) for stage in stages]
        dependency_report = build_brick_house_floor_dependencies(groups)
        predecessors: dict[str, list[str]] = {}
        for group_id, depends_on in dependency_report.edges:
            predecessors.setdefault(group_id, []).append(depends_on)

        with self.store.transaction() as db:
            for table in (
                "stage_instance_projection_summaries", "estimate_quantity_projections",
                "estimate_package_resolutions", "ktp_items", "ktp_groups", "gantt_tasks",
            ):
                db.execute(f"DELETE FROM {table} WHERE estimate_batch_id=?", (batch_id,))

            for stage in stages:
                status = stage.get("projection_generation_status") or "pending"
                db.execute(
                    "INSERT INTO stage_instance_projection_summaries VALUES (?,?,?,?,?)",
                    (_id("summary", batch_id, stage["stage_instance_id"]), batch_id,
                     stage["stage_instance_id"], status, _json_dump(stage)),
                )
            for group in groups:
                meta = {
                    "stage_instance_id": group.stage_instance_id,
                    "template_stage_number": group.template_stage_number,
                    "stage_number": group.stage_number,
                    "floor_number": group.floor_number,
                    "floor_kind": group.floor_kind,
                    "floor_label": group.floor_label,
                    "floor_component": group.floor_component,
                    "component_role": group.component_role,
                }
                db.execute("INSERT INTO ktp_groups VALUES (?,?,?)", (group.id, batch_id, _json_dump(meta)))

            projection_count = item_count = gantt_count = 0
            for row_obj in row_objects:
                estimate_id = str(row_obj.id)
                for projection in row_obj.raw_data.get("ktp_quantity_projections") or []:
                    projection_id = str(projection.get("projection_id") or _id("projection", batch_id, f"{estimate_id}:{projection_count}"))
                    source_key = str(projection.get("source_row_key") or row_obj.raw_data.get("source_row_key"))
                    metadata = dict(projection)
                    db.execute(
                        """INSERT INTO estimate_quantity_projections
                           (id,estimate_batch_id,estimate_id,source_row_key,work_scope_key,applicability,
                            applicability_hash,applicability_hash_version,applicability_schema_version,metadata_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (projection_id, batch_id, estimate_id, source_key,
                         projection.get("work_scope_key"), _json_dump(row_obj.raw_data.get("applicability") or {}),
                         projection.get("applicability_hash"), projection.get("applicability_hash_version"),
                         projection.get("applicability_schema_version"), _json_dump(metadata)),
                    )
                    group_id = _id("ktp-group", batch_id, str(projection.get("stage_instance_id")))
                    lineage = projection_metadata(projection)
                    lineage["group_id"] = group_id
                    lineage["quantity"] = projection.get("quantity")
                    lineage["unit_code"] = projection.get("unit_code")
                    item_id = _id("ktp-item", batch_id, projection_id)
                    db.execute(
                        "INSERT INTO ktp_items VALUES (?,?,?,?,?,?,?,?,?)",
                        (item_id, batch_id, estimate_id, source_key, projection.get("work_scope_key"),
                         projection.get("applicability_hash"), projection.get("applicability_hash_version"),
                         projection.get("applicability_schema_version"), _json_dump(lineage)),
                    )
                    task_meta = dict(lineage)
                    task_meta.update({"task_kind": "leaf", "depends_on_group_ids": predecessors.get(group_id, [])})
                    db.execute(
                        "INSERT INTO gantt_tasks VALUES (?,?,?,?,?,?,?,?,?)",
                        (_id("gantt", batch_id, projection_id), batch_id, estimate_id, source_key,
                         projection.get("work_scope_key"), projection.get("applicability_hash"),
                         projection.get("applicability_hash_version"), projection.get("applicability_schema_version"),
                         _json_dump(task_meta)),
                    )
                    projection_count += 1
                    item_count += 1
                    gantt_count += 1

            milestone_created = dependency_report.milestone is not None
            if dependency_report.milestone is not None:
                milestone = dependency_report.milestone.as_dict()
                db.execute(
                    "INSERT INTO gantt_tasks VALUES (?,?,?,?,?,?,?,?,?)",
                    (_id("gantt", batch_id, STRUCTURAL_COMPLETION_STAGE_INSTANCE_ID), batch_id,
                     None, None, None, None, None, None, _json_dump(milestone)),
                )
                gantt_count += 1
            db.execute(
                "UPDATE estimate_batches SET calculation_status='calculated', calculation_block_reason=NULL WHERE id=?",
                (batch_id,),
            )

        return PostImportPipelineResult(
            batch_id=batch_id,
            stage_instance_count=len(stages),
            quantity_projection_count=projection_count,
            ktp_group_count=len(groups),
            ktp_item_count=item_count,
            gantt_task_count=gantt_count,
            milestone_created=milestone_created,
        )

    @staticmethod
    def _stage_lookup(stages: list[dict[str, Any]]) -> dict[tuple[str, int | None], dict[str, Any]]:
        return {
            (str(stage.get("template_stage_number") or ""), stage.get("floor_number")): stage
            for stage in stages
        }

    @staticmethod
    def _first_operation(stage: Mapping[str, Any]) -> str | None:
        operations = stage.get("operations") or []
        for operation in operations:
            if isinstance(operation, Mapping) and operation.get("operation_code"):
                return str(operation["operation_code"])
        return None
