"""Regression: material/overhead must NOT resolve to work (Gantt/KTP leak)."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.estimate_types import resolve_item_type
from app.services.upload_service import _estimate_item_type as upload_item_type
from app.services.ktp_service import _estimate_item_type as ktp_item_type
from app.api.routes.estimates import _estimate_item_type as route_item_type


def _stub(item_type):
    # No .item_type attribute → forces the raw_data path (like a ParsedRow).
    return SimpleNamespace(raw_data={"item_type": item_type})


def test_resolve_item_type_preserves_all_types():
    for t in ("work", "material", "mechanism", "overhead", "unknown"):
        assert resolve_item_type(_stub(t)) == t


def test_unknown_value_falls_back_to_work():
    assert resolve_item_type(_stub("bogus")) == "work"
    assert resolve_item_type(SimpleNamespace(raw_data=None)) == "work"


def test_helpers_do_not_leak_material_or_overhead_to_work():
    for helper in (upload_item_type, ktp_item_type, route_item_type):
        assert helper(_stub("material")) == "material", helper
        assert helper(_stub("overhead")) == "overhead", helper
        assert helper(_stub("mechanism")) == "mechanism", helper
        assert helper(_stub("work")) == "work", helper
