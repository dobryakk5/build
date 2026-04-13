from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


@pytest.mark.asyncio
async def test_require_superadmin_rejects_regular_user():
    from fastapi import HTTPException
    from app.api.routes.admin import require_superadmin

    with pytest.raises(HTTPException) as exc:
        await require_superadmin(SimpleNamespace(is_superadmin=False))

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_superadmin_allows_superadmin():
    from app.api.routes.admin import require_superadmin

    user = SimpleNamespace(is_superadmin=True)
    assert await require_superadmin(user) is user


@pytest.mark.asyncio
async def test_delete_organization_deletes_loaded_organization():
    from app.api.routes.admin import delete_organization

    organization = SimpleNamespace(id="org-1")
    db = AsyncMock()
    db.get = AsyncMock(return_value=organization)

    response = await delete_organization("org-1", _=SimpleNamespace(is_superadmin=True), db=db)

    db.delete.assert_awaited_once_with(organization)
    db.commit.assert_awaited_once()
    assert response.status_code == 204


def test_user_org_foreign_key_is_cascade():
    from app.models.user import User

    column = User.__table__.c.organization_id
    fk = next(iter(column.foreign_keys))

    assert fk.ondelete == "CASCADE"


def test_organization_users_relationship_is_delete_orphan():
    from app.models.organization import Organization

    cascade = Organization.users.property.cascade

    assert "delete" in cascade
    assert "delete-orphan" in cascade


def _mapping_result(row):
    result = MagicMock()
    mappings = MagicMock()
    mappings.first.return_value = row
    result.mappings.return_value = mappings
    return result


@pytest.mark.asyncio
async def test_update_fer_ignore_updates_whitelisted_table():
    from app.api.routes.admin import FerIgnoreUpdate, update_fer_ignore

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_mapping_result({"id": 17, "ignored": True}))

    result = await update_fer_ignore(
        "table",
        17,
        FerIgnoreUpdate(ignored=True),
        _=SimpleNamespace(is_superadmin=True),
        db=db,
    )

    db.commit.assert_awaited_once()
    assert result == {"entity_kind": "table", "id": 17, "ignored": True}


@pytest.mark.asyncio
async def test_update_fer_ignore_rejects_unknown_kind():
    from fastapi import HTTPException
    from app.api.routes.admin import FerIgnoreUpdate, update_fer_ignore

    with pytest.raises(HTTPException) as exc:
        await update_fer_ignore(
            "row",
            17,
            FerIgnoreUpdate(ignored=True),
            _=SimpleNamespace(is_superadmin=True),
            db=AsyncMock(),
        )

    assert exc.value.status_code == 404
