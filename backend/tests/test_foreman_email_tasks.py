from pathlib import Path
import sys
import time

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def test_make_report_token_round_trip(monkeypatch: pytest.MonkeyPatch):
    from app.tasks.foreman_email_tasks import _make_report_token, verify_report_token

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000)

    token = _make_report_token("report-1")

    assert verify_report_token(token, "report-1") is True
    assert verify_report_token(token, "report-2") is False


def test_verify_report_token_rejects_expired(monkeypatch: pytest.MonkeyPatch):
    from app.tasks.foreman_email_tasks import _make_report_token, verify_report_token

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000)
    token = _make_report_token("report-1")

    monkeypatch.setattr(time, "time", lambda: 1_700_000_000 + 48 * 3600 + 1)

    assert verify_report_token(token, "report-1") is False
