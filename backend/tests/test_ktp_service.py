from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


def make_estimate(
    id: str,
    work_name: str,
    section: str | None = None,
    fer_group_title: str | None = None,
    fer_group_collection_name: str | None = None,
    total_price: float | None = None,
    row_order: int = 0,
):
    estimate = MagicMock()
    estimate.id = id
    estimate.work_name = work_name
    estimate.section = section
    estimate.fer_group_title = fer_group_title
    estimate.fer_group_collection_name = fer_group_collection_name
    estimate.total_price = total_price
    estimate.quantity = None
    estimate.unit = None
    estimate.row_order = row_order
    estimate.deleted_at = None
    estimate.raw_data = {"item_type": "work"}
    return estimate


def make_group(
    id: str = "g1",
    project_id: str = "p1",
    estimate_batch_id: str = "b1",
    title: str = "Фундамент",
    status: str = "new",
    estimate_ids=None,
):
    group = MagicMock()
    group.id = id
    group.project_id = project_id
    group.estimate_batch_id = estimate_batch_id
    group.title = title
    group.status = status
    group.row_count = 3
    group.total_price = 500000
    group.estimate_ids = estimate_ids or ["e1", "e2"]
    group.ktp_card = None
    group.updated_at = None
    return group


def make_card(id: str = "card-1", status: str = "draft"):
    card = MagicMock()
    card.id = id
    card.status = status
    card.updated_at = None
    card.answers_json = None
    card.questions_json = None
    card.steps_json = None
    card.recommendations_json = None
    card.error_message = None
    return card


def test_group_by_section():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Копка котлована", section="Земляные работы"),
        make_estimate("e2", "Вывоз грунта", section="Земляные работы"),
        make_estimate("e3", "Армирование", section="Фундамент"),
    ]
    result = _group_estimates(estimates)
    titles = [row[1] for row in result]
    assert "Земляные работы" in titles
    assert "Фундамент" in titles
    assert len(result) == 2


def test_fallback_to_fer_group_title():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Заливка бетона", fer_group_title="Бетонные работы"),
        make_estimate("e2", "Опалубка", section="", fer_group_title="Бетонные работы"),
        make_estimate("e3", "Монтаж кровли", fer_group_title="Кровельные работы"),
    ]
    result = _group_estimates(estimates)
    assert [row[1] for row in result] == ["Бетонные работы", "Кровельные работы"]


def test_fallback_to_collection_name():
    from app.services.ktp_service import _group_estimates

    result = _group_estimates(
        [
            make_estimate(
                "e1",
                "Штукатурка стен",
                fer_group_collection_name="Отделочные работы",
            )
        ]
    )
    assert result[0][1] == "Отделочные работы"


def test_fallback_to_prochie():
    from app.services.ktp_service import _group_estimates

    result = _group_estimates(
        [
            make_estimate("e1", "Непонятная работа"),
            make_estimate("e2", "Ещё работа"),
        ]
    )
    assert len(result) == 1
    assert result[0][1] == "Прочие работы"


def test_preserves_order():
    from app.services.ktp_service import _group_estimates

    result = _group_estimates(
        [
            make_estimate("e1", "Р1", section="Б"),
            make_estimate("e2", "Р2", section="А"),
            make_estimate("e3", "Р3", section="Б"),
        ]
    )
    assert result[0][1] == "Б"
    assert result[1][1] == "А"


def test_clean_json_strips_markdown():
    from app.services.ktp_service import _clean_json

    assert _clean_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_build_ktp_group_match_text_includes_group_and_works():
    from app.services.ktp_service import _build_ktp_group_match_text

    group = make_group(title="Монтаж потолков")
    estimates = [
        make_estimate("e1", "Устройство каркаса"),
        make_estimate("e2", "Обшивка ГКЛ"),
    ]

    text = _build_ktp_group_match_text(group, estimates)
    assert "Монтаж потолков" in text
    assert "Устройство каркаса" in text
    assert "Обшивка ГКЛ" in text


def test_build_wt_palette_groups_nw_examples_under_wt():
    from app.services.ktp_service import _build_wt_palette

    palette = _build_wt_palette(
        [
            {
                "work_type_code": "WT-01",
                "work_type_name": "Демонтаж",
                "unique_label": "Демонтаж потолков",
            },
            {
                "work_type_code": "WT-01",
                "work_type_name": "Демонтаж",
                "unique_label": "Демонтаж стен",
            },
            {
                "work_type_code": "WT-02",
                "work_type_name": "Монтаж",
                "unique_label": "Монтаж перегородок",
            },
        ]
    )

    assert palette == [
        {
            "wt_code": "WT-01",
            "wt_name": "Демонтаж",
            "examples": ["Демонтаж потолков", "Демонтаж стен"],
        },
        {
            "wt_code": "WT-02",
            "wt_name": "Монтаж",
            "examples": ["Монтаж перегородок"],
        },
    ]


@pytest.mark.asyncio
async def test_batch_wrong_project_raises():
    from app.services.ktp_service import _assert_batch_belongs_to_project

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="не найден в проекте"):
        await _assert_batch_belongs_to_project(db, "project-A", "batch-from-project-B")


@pytest.mark.asyncio
async def test_group_wrong_project_raises():
    from app.services.ktp_service import _assert_group_belongs_to_project

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="не найдена в проекте"):
        await _assert_group_belongs_to_project(db, "project-A", "group-from-project-B")


@pytest.mark.asyncio
async def test_generate_returns_questions_when_insufficient():
    from app.services.ktp_service import generate_ktp_for_group

    fake_group = make_group()
    fake_card = make_card()
    fake_estimates = [make_estimate("e1", "Заливка бетона", section="Фундамент")]

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card", AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group", AsyncMock(return_value=fake_estimates)),
        patch(
            "app.services.ktp_service.create_chat_completion",
            AsyncMock(
                return_value="""{
                    "sufficient": false,
                    "questions": [{"key": "concrete_grade", "label": "Марка бетона?", "type": "text"}]
                }"""
            ),
        ),
    ):
        db = AsyncMock()
        result = await generate_ktp_for_group(db, "p1", "g1")

    assert result["sufficient"] is False
    assert result["questions"][0]["key"] == "concrete_grade"
    assert fake_card.status == "questions_required"
    assert fake_group.status == "questions_required"


@pytest.mark.asyncio
async def test_keyword_match_wt_for_group_sets_wt_fields():
    from app.services.ktp_service import _match_wt_by_keywords_for_ktp_group

    fake_group = make_group(title="Демонтаж потолков")
    fake_estimates = [
        make_estimate("e1", "Демонтаж подвесного потолка"),
        make_estimate("e2", "Демонтаж каркаса потолка"),
    ]

    with patch(
        "app.services.ktp_service.get_palette",
        AsyncMock(
            return_value=[
                {
                    "nw_item_code": "NW-001",
                    "work_type_code": "WT-01",
                    "work_type_name": "Демонтажные работы",
                    "unique_label": "Демонтаж потолков",
                },
                {
                    "nw_item_code": "NW-002",
                    "work_type_code": "WT-02",
                    "work_type_name": "Монтажные работы",
                    "unique_label": "Монтаж потолков",
                },
            ]
        ),
    ), patch(
        "app.services.ktp_service.match_estimate_row",
        side_effect=[
            MagicMock(nw_code="NW-001", confidence="high", note="по ключевому слову: демонтаж"),
            MagicMock(nw_code="NW-001", confidence="high", note="по ключевому слову: демонтаж"),
        ],
    ):
        await _match_wt_by_keywords_for_ktp_group(
            AsyncMock(), fake_group, fake_estimates, 1
        )

    assert fake_group.wt_code == "WT-01"
    assert fake_group.wt_name == "Демонтажные работы"
    assert "По ключевым словам" in fake_group.wt_match_reason
    assert fake_group.wt_match_confidence is not None
    assert fake_group.wt_match_confidence > 0


@pytest.mark.asyncio
async def test_ai_match_wt_for_group_sets_wt_fields():
    from app.services.ktp_service import _match_wt_with_ai_for_ktp_group

    fake_group = make_group(title="Демонтаж потолков")
    fake_estimates = [
        make_estimate("e1", "Разборка подвесного потолка"),
        make_estimate("e2", "Снятие профиля"),
    ]

    with (
        patch(
            "app.services.ktp_service.get_palette",
            AsyncMock(
                return_value=[
                    {
                        "work_type_code": "WT-01",
                        "work_type_name": "Демонтажные работы",
                        "unique_label": "Демонтаж потолков",
                    },
                    {
                        "work_type_code": "WT-02",
                        "work_type_name": "Монтажные работы",
                        "unique_label": "Монтаж потолков",
                    },
                ]
            ),
        ),
        patch(
            "app.services.ktp_service.create_chat_completion",
            AsyncMock(
                return_value="""{
                    "wt_code": "WT-01",
                    "reason": "В группе только работы по разборке существующих элементов.",
                    "confidence": 0.92,
                    "alternatives": ["WT-02"]
                }"""
            ),
        ),
    ):
        await _match_wt_with_ai_for_ktp_group(AsyncMock(), fake_group, fake_estimates, 1)

    assert fake_group.wt_code == "WT-01"
    assert fake_group.wt_name == "Демонтажные работы"
    assert fake_group.wt_match_reason == "В группе только работы по разборке существующих элементов."
    assert fake_group.wt_match_confidence == 0.92
    assert fake_group.wt_match_candidates == [
        {"wt_code": "WT-02", "wt_name": "Монтажные работы"}
    ]


@pytest.mark.asyncio
async def test_generate_returns_ktp_when_sufficient():
    from app.services.ktp_service import generate_ktp_for_group

    fake_group = make_group()
    fake_card = make_card()
    fake_estimates = [make_estimate("e1", "Заливка бетона", section="Фундамент")]

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card", AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group", AsyncMock(return_value=fake_estimates)),
        patch(
            "app.services.ktp_service.create_chat_completion",
            AsyncMock(
                return_value="""{
                    "sufficient": true,
                    "questions": [],
                    "ktp": {
                        "title": "КТП: Фундамент",
                        "goal": "Сделать качественно",
                        "steps": [{"no": 1, "stage": "Подготовка", "work_details": "Детали", "control_points": "Контроль"}],
                        "recommendations": ["Рекомендация"]
                    }
                }"""
            ),
        ),
    ):
        db = AsyncMock()
        result = await generate_ktp_for_group(db, "p1", "g1", {"concrete_grade": "B25"})

    assert result["sufficient"] is True
    assert result["ktp"]["title"] == "КТП: Фундамент"
    assert fake_card.status == "generated"
    assert fake_card.answers_json == {"concrete_grade": "B25"}
    assert fake_group.status == "generated"
