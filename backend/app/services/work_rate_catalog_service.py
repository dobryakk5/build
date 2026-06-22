"""JSON-backed work-rate catalogue used by tests, seed generation and previews.

The production DB adapter can mirror this API.  Keeping a deterministic JSON
catalogue in the delivery package makes the 280-row initial import auditable.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable, TypeVar

from app.services.work_rate_import_service import WorkRateImportService
from app.services.work_rate_mapping_service import MappingResult, WorkRateMappingService
from app.services.work_rate_models import (
    WorkRateImportRun,
    WorkRateItem,
    WorkRateMapping,
    WorkRateSource,
)

T = TypeVar("T")


def _from_dict(cls: type[T], payload: dict[str, Any]) -> T:
    allowed = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in payload.items() if key in allowed})


class WorkRateCatalog:
    FORMAT_VERSION = "1.2.0"

    def __init__(self) -> None:
        self.sources: list[WorkRateSource] = []
        self.items: list[WorkRateItem] = []
        self.mappings: list[WorkRateMapping] = []
        self.import_runs: list[WorkRateImportRun] = []
        self.metadata: dict[str, Any] = {}

    @classmethod
    def load(cls, path: str | Path) -> "WorkRateCatalog":
        catalog = cls()
        path = Path(path)
        if not path.exists():
            return catalog
        payload = json.loads(path.read_text(encoding="utf-8"))
        catalog.sources = [_from_dict(WorkRateSource, row) for row in payload.get("sources", [])]
        catalog.items = [_from_dict(WorkRateItem, row) for row in payload.get("items", [])]
        catalog.mappings = [_from_dict(WorkRateMapping, row) for row in payload.get("mappings", [])]
        catalog.import_runs = [_from_dict(WorkRateImportRun, row) for row in payload.get("import_runs", [])]
        catalog.metadata = dict(payload.get("metadata") or {})
        return catalog

    def save(self, path: str | Path) -> None:
        payload = self.as_dict()
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def as_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.FORMAT_VERSION,
            "metadata": self.metadata,
            "sources": [row.as_dict() for row in self.sources],
            "items": [row.as_dict() for row in self.items],
            "mappings": [row.as_dict() for row in self.mappings],
            "import_runs": [row.as_dict() for row in self.import_runs],
        }

    def active_items_for_source(self, source_id: str) -> list[WorkRateItem]:
        return [item for item in self.items if item.source_id == source_id and item.is_active]

    def import_file(
        self,
        path: str | Path,
        importer: WorkRateImportService | None = None,
    ) -> WorkRateImportRun:
        importer = importer or WorkRateImportService()
        # The source id is deterministic but is known only after parsing; first
        # derive the filename/sheet source by a lightweight import if needed.
        preliminary = importer.import_file(path)
        duplicate = next(
            (
                run
                for run in self.import_runs
                if run.source_id == preliminary.source.id
                and run.file_hash == preliminary.run.file_hash
                and run.status.startswith("completed")
            ),
            None,
        )
        if duplicate:
            return duplicate

        previous = self.active_items_for_source(preliminary.source.id)
        result = preliminary if not previous else importer.import_file(path, previous_items=previous)

        source_index = {source.id: index for index, source in enumerate(self.sources)}
        if result.source.id in source_index:
            self.sources[source_index[result.source.id]] = result.source
        else:
            self.sources.append(result.source)

        item_index = {item.id: index for index, item in enumerate(self.items)}
        active_by_stable = {
            item.stable_row_key: item
            for item in self.items
            if item.is_active and item.source_id == result.source.id
        }
        for item in result.items:
            previous_item = active_by_stable.get(item.stable_row_key)
            if previous_item and previous_item.id != item.id and item.supersedes_rate_item_id == previous_item.id:
                previous_item.is_active = False
            if item.id in item_index:
                self.items[item_index[item.id]] = item
            else:
                self.items.append(item)

        self.import_runs.append(result.run)
        return result.run

    def auto_map(
        self,
        mapper: WorkRateMappingService,
        *,
        remap_existing: bool = False,
    ) -> list[MappingResult]:
        results: list[MappingResult] = []
        active_mapping_items = {mapping.rate_item_id for mapping in self.mappings if mapping.is_active}
        for item in self.items:
            if not item.is_active:
                continue
            if item.id in active_mapping_items and not remap_existing:
                continue
            result = mapper.map_item(item)
            results.append(result)
            if remap_existing:
                for mapping in self.mappings:
                    if mapping.rate_item_id == item.id and mapping.mapping_source != "manual":
                        mapping.is_active = False
            self.mappings.extend(result.mappings)
        self.refresh_mapping_aggregates()
        return results

    def refresh_mapping_aggregates(self) -> None:
        by_item: dict[str, list[WorkRateMapping]] = {}
        for mapping in self.mappings:
            if mapping.is_active:
                by_item.setdefault(mapping.rate_item_id, []).append(mapping)
        for item in self.items:
            active = by_item.get(item.id, [])
            item.has_active_mapping = bool(active)
            if not active:
                continue
            modes = {mapping.mapping_mode for mapping in active}
            if modes == {"excluded"}:
                item.mapping_status = "excluded"
            elif modes == {"observation"}:
                item.mapping_status = "observation"
            elif any(mapping.taxonomy_code for mapping in active):
                item.mapping_status = "mapped" if item.auto_applicable else "partially_mapped"

    def active_mappings(self) -> Iterable[WorkRateMapping]:
        return (mapping for mapping in self.mappings if mapping.is_active)
