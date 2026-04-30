from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_user(id="u1", org_id="org-A", is_active=True):
    user = MagicMock()
    user.id = id
    user.organization_id = org_id
    user.is_active = is_active
    user.email = f"{id}@example.com"
    user.name = f"User {id}"
    user.avatar_url = None
    user.email_verified_at = "2024-01-01"
    return user


def make_member(project_id="p1", user_id="u1", role="owner", member_id="m1"):
    member = MagicMock()
    member.id = member_id
    member.project_id = project_id
    member.user_id = user_id
    member.role = role
    member.invited_by = None
    member.created_at = MagicMock()
    member.created_at.isoformat.return_value = "2024-01-01T00:00:00"
    return member


def make_project(id="p1", org_id="org-A", deleted_at=None):
    project = MagicMock()
    project.id = id
    project.organization_id = org_id
    project.name = f"Project {id}"
    project.address = None
    project.status = "active"
    project.dashboard_status = "green"
    project.color = None
    project.start_date = None
    project.end_date = None
    project.deleted_at = deleted_at
    project.created_at = MagicMock()
    project.created_at.isoformat.return_value = "2024-01-01T00:00:00"
    return project


@pytest.mark.asyncio
async def test_add_member_rejects_cross_org_user():
    from fastapi import HTTPException
    from app.api.routes.projects import add_member

    current_user = make_user(id="admin", org_id="org-A")
    target_user = make_user(id="intruder", org_id="org-B")
    invoker_member = make_member(user_id="admin", role="owner")

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.get = AsyncMock(return_value=target_user)

    body = SimpleNamespace(user_id="intruder", role="viewer")

    with pytest.raises(HTTPException) as exc:
        await add_member(
            project_id="p1",
            body=body,
            member=invoker_member,
            current_user=current_user,
            db=db,
        )

    assert exc.value.status_code == 403
    assert "другой организации" in exc.value.detail


@pytest.mark.asyncio
async def test_list_projects_query_count():
    from app.api.routes.projects import list_projects

    current_user = make_user()
    memberships = [
        make_member(project_id="p1", user_id="u1", role="owner", member_id="m1"),
        make_member(project_id="p2", user_id="u1", role="pm", member_id="m2"),
        make_member(project_id="p3", user_id="u1", role="viewer", member_id="m3"),
    ]
    projects = [make_project(id="p1"), make_project(id="p2"), make_project(id="p3")]

    call_count = 0

    async def fake_scalars(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return iter(memberships)
        return iter(projects)

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 6:
            rows = [
                SimpleNamespace(project_id="p1", workers_count=4),
                SimpleNamespace(project_id="p2", workers_count=7),
            ]
        else:
            rows = []
        mock_result.__iter__ = MagicMock(return_value=iter(rows))
        return mock_result

    db = MagicMock()
    db.scalars = fake_scalars
    db.execute = fake_execute

    result = await list_projects(current_user=current_user, db=db)

    assert call_count == 6
    assert len(result) == 3
    assert result[0]["workers_count"] == 4
    assert result[1]["workers_count"] == 7
    assert result[2]["workers_count"] is None


@pytest.mark.asyncio
async def test_list_members_query_count():
    from app.api.routes.projects import list_members

    members = [
        make_member(project_id="p1", user_id="u1", role="owner", member_id="m1"),
        make_member(project_id="p1", user_id="u2", role="pm", member_id="m2"),
        make_member(project_id="p1", user_id="u3", role="viewer", member_id="m3"),
    ]
    users = [make_user(id="u1"), make_user(id="u2"), make_user(id="u3")]

    call_count = 0

    async def fake_scalars(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return iter(members)
        return iter(users)

    db = MagicMock()
    db.scalars = fake_scalars

    result = await list_members(project_id="p1", member=make_member(), db=db)

    assert call_count == 2
    assert len(result) == 3
