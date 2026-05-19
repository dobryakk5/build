from pathlib import Path
import logging
import sys

import pytest
from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api.routes.estimates import (  # noqa: E402
    _normalize_clarification_payload,
    _parse_clarification_answers,
    _public_clarification_answers,
)
from app.services.ktp_estimate_service import (  # noqa: E402
    _format_clarification_answers_for_prompt,
    _merge_group_answers_into_batch,
)


def test_normalize_clarification_payload_keeps_question_text_and_filters_unknown():
    payload = {
        "version": "v1",
        "estimate_kind": 1,
        "kind_title": "Земляные / грунтовые работы",
        "form": {
            "1.1": {
                "section": "Технология",
                "question": "Тип грунта",
                "answers": ["Песок", "Требуется уточнить", "Песок"],
            },
            "1.2": {
                "section": "Технология",
                "question": "Форма выемки",
                "answers": [],
            },
        },
    }

    assert _normalize_clarification_payload(payload) == {
        "version": "v1",
        "estimate_kind": 1,
        "kind_title": "Земляные / грунтовые работы",
        "form": {
            "1.1": {
                "section": "Технология",
                "question": "Тип грунта",
                "answers": ["Песок"],
            }
        },
    }


def test_normalize_clarification_payload_rejects_legacy_shape():
    with pytest.raises(HTTPException) as exc:
        _normalize_clarification_payload({"1.1": ["Песок"]})

    assert exc.value.status_code == 400


def test_parse_clarification_answers_rejects_reserved_keys_recursively():
    with pytest.raises(HTTPException) as exc:
        _parse_clarification_answers(
            '{"version":"v1","form":{"1.1":{"question":"Q","answers":["A"],"__bad":true}}}'
        )

    assert exc.value.status_code == 400
    assert "Служебный ключ" in exc.value.detail


def test_public_clarification_answers_hides_stage3():
    assert _public_clarification_answers(
        {
            "version": "v1",
            "estimate_kind": 1,
            "form": {"1.1": {"question": "Тип грунта", "answers": ["Песок"]}},
            "stage3": {"group": {"answers": {}}},
        }
    ) == {
        "version": "v1",
        "estimate_kind": 1,
        "form": {"1.1": {"question": "Тип грунта", "answers": ["Песок"]}},
    }


def test_format_clarification_answers_uses_question_text_and_stage3():
    prompt_block = _format_clarification_answers_for_prompt(
        {
            "version": "v1",
            "form": {
                "1.1": {
                    "section": "Технология",
                    "question": "Тип грунта",
                    "answers": ["Песок"],
                },
            },
            "stage3": {
                "g1": {
                    "group_title": "Котлован",
                    "answers": {
                        "water": {
                            "question": "Нужно ли водопонижение?",
                            "answer": "Да",
                        }
                    },
                }
            },
        }
    )

    assert "Технология / Тип грунта: Песок" in prompt_block
    assert "Котлован — Нужно ли водопонижение?: Да" in prompt_block
    assert "1.1: Песок" not in prompt_block


def test_format_clarification_answers_prioritizes_current_group_and_warns(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        "app.services.ktp_estimate_service.MAX_PROMPT_CLARIFICATION_LINES",
        3,
    )
    payload = {
        "version": "v1",
        "form": {
            "1.1": {
                "section": "Технология",
                "question": "Тип грунта",
                "answers": ["Песок"],
            },
        },
        "stage3": {
            "other": {
                "group_title": "Другая группа",
                "answers": {
                    "other": {"question": "Поздний вопрос", "answer": "Поздний ответ"}
                },
            },
            "current": {
                "group_title": "Текущая группа",
                "answers": {
                    "first": {"question": "Первый вопрос", "answer": "Первый ответ"},
                    "second": {"question": "Второй вопрос", "answer": "Второй ответ"},
                },
            },
        },
    }

    with caplog.at_level(logging.WARNING):
        prompt_block = _format_clarification_answers_for_prompt(
            payload,
            current_group_id="current",
        )

    assert "Clarification prompt context truncated" in caplog.text
    lines = prompt_block.splitlines()
    assert "Текущая группа — Первый вопрос: Первый ответ" in lines[1]
    assert "Текущая группа — Второй вопрос: Второй ответ" in lines[2]
    assert "Технология / Тип грунта: Песок" in lines[3]
    assert "Другая группа" not in prompt_block


def test_merge_group_answers_preserves_legacy_and_existing_stage3(monkeypatch):
    monkeypatch.setattr(
        "app.services.ktp_estimate_service.flag_modified",
        lambda *_args, **_kwargs: None,
    )

    class Batch:
        clarification_answers = {
            "version": "v1",
            "__ktp_stage3": {
                "legacy-group": {
                    "group_title": "Старая группа",
                    "answers": {"old": {"question": "Старый вопрос", "answer": "Да"}},
                }
            },
            "stage3": {
                "existing-group": {
                    "group_title": "Новая группа",
                    "answers": {"new": {"question": "Новый вопрос", "answer": "Нет"}},
                }
            },
        }

    class Group:
        id = "current-group"
        title = "Текущая группа"
        card_questions_json = [{"key": "water", "label": "Нужно ли водопонижение?"}]

    batch = Batch()
    _merge_group_answers_into_batch(batch, Group(), {"water": "Да"}, source="known_context")

    assert "__ktp_stage3" not in batch.clarification_answers
    stage3 = batch.clarification_answers["stage3"]
    assert stage3["legacy-group"]["answers"]["old"]["answer"] == "Да"
    assert stage3["existing-group"]["answers"]["new"]["answer"] == "Нет"
    assert stage3["current-group"]["answers"]["water"] == {
        "question": "Нужно ли водопонижение?",
        "answer": "Да",
        "source": "known_context",
    }
