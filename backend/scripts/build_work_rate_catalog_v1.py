from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.work_rate_catalog_service import WorkRateCatalog
from app.services.work_rate_mapping_service import WorkRateMappingService

NORMALIZED_FILES = (
    "Жилое остальные дома.xlsx",
    "Расценки на ландшафтные работы.xlsx",
    "Расценки №1 11 июня 2026.xlsx",
    "Строит-во каркасного дома.xlsx",
    "Фахверк.xlsx",
)
OBSERVATION_FILES = ("грунтовые работы.xlsx",)


def build(source_dir: Path, taxonomy: Path, output: Path, summary_output: Path) -> dict:
    catalog = WorkRateCatalog()
    for filename in (*NORMALIZED_FILES, *OBSERVATION_FILES):
        path = source_dir / filename
        if not path.exists():
            raise FileNotFoundError(path)
        catalog.import_file(path)

    mapper = WorkRateMappingService(taxonomy)
    catalog.auto_map(mapper)
    catalog.metadata.update(
        {
            "rate_catalog_version": "work_rate_catalog_v1@1.2.0",
            "taxonomy_version": mapper.taxonomy_version,
            "operation_policy_version": mapper.policy_version,
            "source_files": [*NORMALIZED_FILES, *OBSERVATION_FILES],
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog.save(output)

    source_kind_by_id = {source.id: source.source_kind for source in catalog.sources}
    summary = {
        "rate_catalog_version": catalog.metadata["rate_catalog_version"],
        "taxonomy_version": mapper.taxonomy_version,
        "operation_policy_version": mapper.policy_version,
        "normalized_items": sum(
            1 for item in catalog.items
            if source_kind_by_id.get(item.source_id) == "normalized_rate_catalog"
        ),
        "observation_items": sum(
            1 for item in catalog.items
            if source_kind_by_id.get(item.source_id) == "market_estimate_observation"
        ),
        "mapping_status_counts": dict(Counter(item.mapping_status for item in catalog.items)),
        "review_status_counts": dict(Counter(item.review_status for item in catalog.items)),
        "row_role_counts": dict(Counter(item.row_role for item in catalog.items)),
        "operation_detected_count": sum(
            1 for item in catalog.items
            if any(m.is_active and m.rate_item_id == item.id and m.operation_code for m in catalog.mappings)
        ),
        "operation_undetected_count": sum(
            1 for item in catalog.items
            if not any(m.is_active and m.rate_item_id == item.id and m.operation_code for m in catalog.mappings)
        ),
        "auto_applicable_work_items": sum(
            1 for item in catalog.items if item.row_role == "work" and item.auto_applicable
        ),
        "mappings_count": sum(1 for mapping in catalog.mappings if mapping.is_active),
    }
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "construction_work_dictionary_v6_4_11.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "work_rate_catalog_v1.json",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "work_rate_catalog_v1_summary.json",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.source_dir, args.taxonomy, args.output, args.summary_output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
