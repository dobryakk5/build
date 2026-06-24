from __future__ import annotations

from uuid import UUID, uuid4, uuid5


TAXONOMY_SOURCE_ROW_NAMESPACE = UUID("87a63bb7-9041-59aa-bdfe-4418504ccae8")


def normalize_uuid(value) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def new_source_row_key() -> str:
    return str(uuid4())


def legacy_source_row_key(estimate_batch_id: str, estimate_id: str) -> str:
    return str(uuid5(TAXONOMY_SOURCE_ROW_NAMESPACE, f"{estimate_batch_id}:{estimate_id}"))


def resolve_work_scope_key(source_row_key: str | None, estimate_id: str | None = None) -> str:
    if source_row_key:
        return f"source_row:{source_row_key}"
    if estimate_id:
        return f"estimate_row:{estimate_id}"
    return f"source_row:{new_source_row_key()}"
