# backend/tests/test_ktp_service.py
"""
Тесты для ktp_service:
- группировка строк сметы по section / fer_group_title / fallback
- идемпотентность build_ktp_groups_for_batch
- защита от IDOR (чужой batch_id / group_id)
- парсинг ответа LLM (questions / generated / error / invalid JSON)
"""
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_estimate(
    id: str,
    work_name: str,
    section: str | None = None,
    fer_group_title: str | None = None,
    fer_group_collection_name: str | None = None,
    total_price: float | None = None,
    row_order: int = 0,
):
    e = MagicMock()
    e.id = id
    e.work_name = work_name
    e.section = section
    e.fer_group_title = fer_group_title
    e.fer_group_collection_name = fer_group_collection_name
    e.total_price = total_price
    e.quantity = None
    e.unit = None
    e.row_order = row_order
    e.deleted_at = None
    return e


def make_group(
    id: str = "g1",
    project_id: str = "p1",
    estimate_batch_id: str = "b1",
    title: str = "Фундамент",
    status: str = "new",
    estimate_ids=None,
):
    g = MagicMock()
    g.id = id
    g.project_id = project_id
    g.estimate_batch_id = estimate_batch_id
    g.title = title
    g.status = status
    g.row_count = 3
    g.total_price = 500000
    g.estimate_ids = estimate_ids or ["e1", "e2"]
    g.ktp_card = None
    # updated_at нужен как settable attr
    g.updated_at = None
    return g


def make_card(id: str = "card-1", status: str = "draft"):
    c = MagicMock()
    c.id = id
    c.status = status
    c.updated_at = None
    c.answers_json = None
    c.questions_json = None
    c.steps_json = None
    c.recommendations_json = None
    c.error_message = None
    return c


# ─── _group_estimates: section priority ──────────────────────────────────────

def test_group_by_section():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Копка котлована", section="Земляные работы"),
        make_estimate("e2", "Вывоз грунта",    section="Земляные работы"),
        make_estimate("e3", "Армирование",     section="Фундамент"),
    ]
    result = _group_estimates(estimates)
    titles = [r[1] for r in result]
    assert "Земляные работы" in titles
    assert "Фундамент" in titles
    assert len(result) == 2
    zem = next(r for r in result if r[1] == "Земляные работы")
    assert len(zem[2]) == 2


def test_fallback_to_fer_group_title():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Заливка бетона", section=None, fer_group_title="Бетонные работы"),
        make_estimate("e2", "Опалубка",        section="",   fer_group_title="Бетонные работы"),
        make_estimate("e3", "Монтаж кровли",   section=None, fer_group_title="Кровельные работы"),
    ]
    result = _group_estimates(estimates)
    titles = [r[1] for r in result]
    assert "Бетонные работы" in titles
    assert "Кровельные работы" in titles


def test_fallback_to_collection_name():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate(
            "e1", "Штукатурка стен",
            section=None, fer_group_title=None,
            fer_group_collection_name="Отделочные работы",
        ),
    ]
    result = _group_estimates(estimates)
    assert result[0][1] == "Отделочные работы"


def test_fallback_to_prochie():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Непонятная работа", section=None, fer_group_title=None),
        make_estimate("e2", "Ещё работа",        section=None, fer_group_title=None),
    ]
    result = _group_estimates(estimates)
    assert len(result) == 1
    assert result[0][1] == "Прочие работы"
    assert len(result[0][2]) == 2


def test_section_takes_priority_over_fer():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Работа", section="Мой раздел", fer_group_title="ФЕР-группа"),
    ]
    result = _group_estimates(estimates)
    assert result[0][1] == "Мой раздел"


def test_mixed_groups():
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Работа А", section="Раздел 1"),
        make_estimate("e2", "Работа Б", section="Раздел 1"),
        make_estimate("e3", "Работа В", section=None, fer_group_title="ФЕР группа"),
        make_estimate("e4", "Работа Г", section=None, fer_group_title=None),
    ]
    result = _group_estimates(estimates)
    assert len(result) == 3  # Раздел 1, ФЕР группа, Прочие работы


def test_preserves_order():
    """Группы идут в порядке первого появления в списке."""
    from app.services.ktp_service import _group_estimates

    estimates = [
        make_estimate("e1", "Р1", section="Б"),
        make_estimate("e2", "Р2", section="А"),
        make_estimate("e3", "Р3", section="Б"),
    ]
    result = _group_estimates(estimates)
    assert result[0][1] == "Б"
    assert result[1][1] == "А"


# ─── _slugify ─────────────────────────────────────────────────────────────────

def test_slugify_cyrillic():
    from app.services.ktp_service import _slugify
    key = _slugify("Земляные работы")
    assert " " not in key
    assert key == key.lower()


def test_slugify_idempotent():
    from app.services.ktp_service import _slugify
    assert _slugify("Фундамент") == _slugify("Фундамент")


def test_slugify_different_keys():
    from app.services.ktp_service import _slugify
    assert _slugify("Кровля") != _slugify("Фундамент")


# ─── IDOR guards ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_wrong_project_raises():
    from app.services.ktp_service import _assert_batch_belongs_to_project

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="не найден в проекте"):
        await _assert_batch_belongs_to_project(db, "project-A", "batch-from-project-B")


@pytest.mark.asyncio
async def test_batch_correct_project_ok():
    from app.services.ktp_service import _assert_batch_belongs_to_project

    fake_batch = MagicMock()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=fake_batch)

    result = await _assert_batch_belongs_to_project(db, "p1", "b1")
    assert result is fake_batch


@pytest.mark.asyncio
async def test_group_wrong_project_raises():
    from app.services.ktp_service import _assert_group_belongs_to_project

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="не найдена в проекте"):
        await _assert_group_belongs_to_project(db, "project-A", "group-from-project-B")


# ─── _clean_json ─────────────────────────────────────────────────────────────

def test_clean_json_strips_markdown():
    from app.services.ktp_service import _clean_json
    assert _clean_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_clean_json_plain():
    from app.services.ktp_service import _clean_json
    assert _clean_json('{"a": 1}') == '{"a": 1}'


def test_clean_json_strips_whitespace():
    from app.services.ktp_service import _clean_json
    assert _clean_json('  \n{"a": 1}\n  ') == '{"a": 1}'


# ─── generate_ktp_for_group ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_returns_questions_when_insufficient():
    from app.services.ktp_service import generate_ktp_for_group

    llm_json = """{
        "sufficient": false,
        "questions": [
            {"key": "concrete_grade", "label": "Марка бетона?", "type": "text", "hint": "B25"}
        ]
    }"""

    fake_group = make_group()
    fake_card = make_card()

    db = AsyncMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card",               AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group",          AsyncMock(return_value=[])),
        patch("app.services.ktp_service.create_chat_completion",             AsyncMock(return_value=llm_json)),
    ):
        result = await generate_ktp_for_group(db, "p1", "g1")

    assert result["sufficient"] is False
    assert len(result["questions"]) == 1
    assert result["questions"][0]["key"] == "concrete_grade"
    assert fake_card.status == "questions_required"
    assert fake_group.status == "questions_required"


@pytest.mark.asyncio
async def test_generate_returns_ktp_when_sufficient():
    from app.services.ktp_service import generate_ktp_for_group

    llm_json = """{
        "sufficient": true,
        "questions": [],
        "ktp": {
            "title": "КТП: Фундамент",
            "goal": "Обеспечить качество",
            "steps": [
                {"no": 1, "stage": "Подготовка", "work_details": "Разбивка осей", "control_points": "Нивелировка"}
            ],
            "recommendations": ["Бетонировать непрерывно"]
        }
    }"""

    fake_group = make_group()
    fake_card = make_card()

    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card",               AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group",          AsyncMock(return_value=[])),
        patch("app.services.ktp_service.create_chat_completion",             AsyncMock(return_value=llm_json)),
    ):
        result = await generate_ktp_for_group(db, "p1", "g1")

    assert result["sufficient"] is True
    assert result["ktp"]["title"] == "КТП: Фундамент"
    assert len(result["ktp"]["steps"]) == 1
    assert fake_card.status == "generated"
    assert fake_group.status == "generated"


@pytest.mark.asyncio
async def test_generate_with_answers_saves_them():
    from app.services.ktp_service import generate_ktp_for_group

    llm_json = '{"sufficient": true, "questions": [], "ktp": {"title": "T", "goal": "G", "steps": [], "recommendations": []}}'
    fake_group = make_group()
    fake_card = make_card()
    answers = {"concrete_grade": "B30", "rebar_class": "A500"}

    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card",               AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group",          AsyncMock(return_value=[])),
        patch("app.services.ktp_service.create_chat_completion",             AsyncMock(return_value=llm_json)),
    ):
        await generate_ktp_for_group(db, "p1", "g1", answers=answers)

    assert fake_card.answers_json == answers


@pytest.mark.asyncio
async def test_generate_llm_error_sets_failed():
    from app.services.ktp_service import generate_ktp_for_group

    fake_group = make_group()
    fake_card = make_card()

    db = AsyncMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card",               AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group",          AsyncMock(return_value=[])),
        patch("app.services.ktp_service.create_chat_completion",             AsyncMock(side_effect=RuntimeError("timeout"))),
    ):
        with pytest.raises(RuntimeError):
            await generate_ktp_for_group(db, "p1", "g1")

    assert fake_card.status == "failed"
    assert "timeout" in fake_card.error_message


@pytest.mark.asyncio
async def test_generate_invalid_json_raises():
    from app.services.ktp_service import generate_ktp_for_group

    fake_group = make_group()
    fake_card = make_card()

    db = AsyncMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_group_belongs_to_project", AsyncMock(return_value=fake_group)),
        patch("app.services.ktp_service._get_or_create_card",               AsyncMock(return_value=fake_card)),
        patch("app.services.ktp_service._load_estimates_for_group",          AsyncMock(return_value=[])),
        patch("app.services.ktp_service.create_chat_completion",             AsyncMock(return_value="не JSON")),
    ):
        with pytest.raises(ValueError, match="невалидный JSON"):
            await generate_ktp_for_group(db, "p1", "g1")

    assert fake_card.status == "failed"


# ─── build_ktp_groups_for_batch: idempotency ─────────────────────────────────

@pytest.mark.asyncio
async def test_build_groups_idempotent():
    """force=False: если группы уже есть — db.add не вызывается."""
    from app.services.ktp_service import build_ktp_groups_for_batch

    existing = [make_group("g1"), make_group("g2")]

    db = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_batch_belongs_to_project", AsyncMock(return_value=MagicMock())),
        patch("app.services.ktp_service.get_ktp_groups",                    AsyncMock(return_value=existing)),
    ):
        result = await build_ktp_groups_for_batch(db, "p1", "b1", force=False)

    assert result is existing
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_build_groups_empty_estimates_returns_empty():
    """Если в смете нет строк — возвращаем пустой список."""
    from app.services.ktp_service import build_ktp_groups_for_batch

    db = AsyncMock()
    # scalars() возвращает пустой итератор
    db.scalars = AsyncMock(return_value=iter([]))
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.ktp_service._assert_batch_belongs_to_project", AsyncMock(return_value=MagicMock())),
        patch("app.services.ktp_service.get_ktp_groups",                    AsyncMock(return_value=[])),
    ):
        result = await build_ktp_groups_for_batch(db, "p1", "b1", force=False)

    assert result == []
