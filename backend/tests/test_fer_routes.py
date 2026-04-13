from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_fer_collections_return_ignore_flags(monkeypatch):
    from app.api.routes import fer as fer_routes

    async def fake_fetch_all(db, sql, params):
        return [
            {
                "id": 1,
                "num": "01",
                "name": "Земляные работы",
                "ignored": True,
                "effective_ignored": True,
                "sections_count": 2,
                "subsections_count": 3,
                "total_tables_count": 4,
                "root_tables_count": 1,
            }
        ]

    monkeypatch.setattr(fer_routes, "_fetch_all", fake_fetch_all)

    result = await fer_routes.fer_collections(db=AsyncMock())

    assert result[0]["ignored"] is True
    assert result[0]["effective_ignored"] is True


@pytest.mark.asyncio
async def test_fer_search_returns_ignore_flags(monkeypatch):
    from app.api.routes import fer as fer_routes

    async def fake_fetch_all(db, sql, params):
        return [
            {
                "table_id": 15,
                "table_title": "Монтаж перекрытий",
                "row_count": 5,
                "table_url": "/fer/15",
                "common_work_name": "Монтаж перекрытий",
                "collection_id": 1,
                "collection_num": "01",
                "collection_name": "Сборник",
                "collection_ignored": False,
                "section_id": 2,
                "section_title": "Раздел",
                "section_ignored": True,
                "subsection_id": None,
                "subsection_title": None,
                "subsection_ignored": False,
                "ignored": False,
                "effective_ignored": True,
                "match_scope": "section",
                "matched_text": "Раздел",
                "matching_rows_count": 0,
            }
        ]

    monkeypatch.setattr(fer_routes, "_fetch_all", fake_fetch_all)

    result = await fer_routes.fer_search(q="перекрытия", db=AsyncMock())

    assert result[0]["ignored"] is False
    assert result[0]["effective_ignored"] is True
    assert result[0]["section"]["effective_ignored"] is True
