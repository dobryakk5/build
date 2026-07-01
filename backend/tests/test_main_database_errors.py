import json
import logging
from pathlib import Path
import sys

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import database_unavailable_handler


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/projects",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
    })


@pytest.mark.asyncio
async def test_dbapi_error_without_connectivity_is_not_reported_as_database_unavailable(caplog):
    exc = DBAPIError("SELECT", {}, RuntimeError("value too long"))

    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = await database_unavailable_handler(_request(), exc)

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "database_error"}}
    assert "Unhandled database error on GET /projects" in caplog.text
    assert "value too long" in caplog.text


@pytest.mark.asyncio
async def test_operational_connectivity_error_is_reported_as_database_unavailable(caplog):
    exc = OperationalError("SELECT", {}, asyncpg.PostgresConnectionError("connection refused"))

    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = await database_unavailable_handler(_request(), exc)

    assert response.status_code == 503
    assert json.loads(response.body) == {"detail": {"code": "database_unavailable"}}
    assert "Database connectivity error on GET /projects" in caplog.text
    assert "connection refused" in caplog.text
