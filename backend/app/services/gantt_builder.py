"""
backend/app/services/gantt_builder.py

Строит задачи Ганта из распарсенных строк сметы.
Использует нормы ЕНиР для расчёта длительности в рабочих днях.
Возвращает DTO-объекты + список зависимостей.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from app.services.gantt_calculations import (
    DEFAULT_HOURS_PER_DAY,
    calculate_labor_hours,
    calculate_working_days,
)


# ── Нормы трудоёмкости (упрощённый справочник ЕНиР) ─────────────────────────
# В продакшне — полноценная таблица enir_norms в БД (~5000 позиций)

ENIR_NORMS: dict[str, dict] = {
    "земляные работы":       {"hours": 0.5,  "workers": 3},
    "разработка грунта":     {"hours": 0.4,  "workers": 3},
    "вывоз грунта":          {"hours": 0.3,  "workers": 2},
    "уплотнение":            {"hours": 0.4,  "workers": 2},
    "фундамент":             {"hours": 2.0,  "workers": 4},
    "щебёночная подготовка": {"hours": 0.8,  "workers": 2},
    "армирование":           {"hours": 18.0, "workers": 3},  # часов на тонну
    "опалубка":              {"hours": 1.2,  "workers": 3},
    "бетонирование":         {"hours": 1.5,  "workers": 4},
    "кладка":                {"hours": 1.8,  "workers": 3},
    "перекрытия":            {"hours": 0.8,  "workers": 4},
    "армопояс":              {"hours": 1.2,  "workers": 3},
    "кровля":                {"hours": 1.2,  "workers": 3},
    "стропил":               {"hours": 2.5,  "workers": 3},
    "гидроизоляция":         {"hours": 0.3,  "workers": 2},
    "утеплитель":            {"hours": 0.4,  "workers": 2},
    "металлочерепица":       {"hours": 0.9,  "workers": 2},
    "водосточная":           {"hours": 0.6,  "workers": 2},
    "мауэрлат":              {"hours": 1.0,  "workers": 2},
    "электромонтаж":         {"hours": 0.8,  "workers": 2},
    "отопление":             {"hours": 1.0,  "workers": 2},
    "водоснабжение":         {"hours": 0.9,  "workers": 2},
    "канализация":           {"hours": 0.9,  "workers": 2},
    "вентиляция":            {"hours": 1.5,  "workers": 2},
    "окна":                  {"hours": 3.0,  "workers": 2},
    "двери":                 {"hours": 2.5,  "workers": 2},
    "штукатурка":            {"hours": 0.5,  "workers": 3},
    "стяжка":                {"hours": 0.3,  "workers": 2},
    "плитка":                {"hours": 1.0,  "workers": 2},
    "обои":                  {"hours": 0.4,  "workers": 2},
    "ламинат":               {"hours": 0.4,  "workers": 2},
    "гипсокартон":           {"hours": 0.6,  "workers": 2},
    "отделка":               {"hours": 0.7,  "workers": 3},
    "фасад":                 {"hours": 0.8,  "workers": 3},
    "грунтование":           {"hours": 0.2,  "workers": 1},
    "благоустройство":       {"hours": 0.5,  "workers": 3},
}

# Технологическая последовательность разделов
SECTION_ORDER = [
    "подготовительн", "разбивка", "ограждение",
    "земляные", "разработка", "вывоз",
    "фундамент", "щебёночн", "армирован", "опалубка", "бетонирован",
    "цоколь", "гидроизол",
    "кладка", "стен", "перекрыт", "армопояс",
    "кровля", "стропил", "мауэрлат", "утеплит", "металлочерепиц", "водосточн",
    "окна", "двери", "фасад",
    "электро", "отоплен", "водоснабжен", "канализац", "вентилц",
    "штукатурк", "стяжка", "плитка", "обои", "ламинат", "гипсокартон",
    "отделка", "потолок",
    "благоустройств",
]

SECTION_COLORS = {
    "подготовит": "#6366f1", "земляные": "#d97706",  "разработка": "#d97706",
    "фундамент":  "#dc2626", "кладка":   "#0284c7",  "перекрыт":   "#0284c7",
    "кровля":     "#0f766e", "стропил":  "#0f766e",
    "электро":    "#7c3aed", "отоплен":  "#7c3aed",  "водоснабж":  "#7c3aed",
    "окна":       "#0369a1", "двери":    "#0369a1",
    "фасад":      "#b45309", "штукатурк":"#059669",  "отделка":    "#059669",
}


# ── DTO ───────────────────────────────────────────────────────────────────────

@dataclass
class GanttTaskDTO:
    id:          str
    project_id:  str
    estimate_id: str | None
    parent_id:   str | None
    name:        str
    start_date:  date
    working_days: int
    workers_count: int | None
    labor_hours: float | None
    hours_per_day: float
    is_group:    bool
    type:        str       # task | project
    color:       str
    row_order:   float = field(default=1000.0)


# ── Builder ───────────────────────────────────────────────────────────────────

class GanttBuilder:
    HOURS_PER_DAY = DEFAULT_HOURS_PER_DAY

    def build(
        self,
        project_id: str,
        estimates:  list,       # list[Estimate ORM objects]
        start_date: date,
        workers:    int = 3,
        hours_per_day: float = DEFAULT_HOURS_PER_DAY,
        fer_hours_by_table_id: dict[int, float] | None = None,
    ) -> list[GanttTaskDTO]:
        """
        Алгоритм:
        1. Идём по строкам сметы в row_order
        2. Строим вложенные группы по raw_data.group_path, если он есть
        4. После импорта все группы и задачи стартуют с одной даты
        5. Зависимости оператор проставляет вручную
        """
        tasks: list[GanttTaskDTO] = []
        effective_hours_per_day = float(hours_per_day or self.HOURS_PER_DAY)
        effective_fer_hours_by_table_id = fer_hours_by_table_id or {}
        ordered_estimates = sorted(
            estimates,
            key=lambda est: (
                getattr(est, "row_order", 0),
                getattr(est, "created_at", None) or "",
                getattr(est, "id", ""),
            ),
        )

        row_order = 1000.0
        group_stack: list[tuple[str, GanttTaskDTO]] = []

        for est in ordered_estimates:
            group_path = self._estimate_group_path(est)
            color = self._section_color(group_path[0])

            common_depth = 0
            max_common = min(len(group_stack), len(group_path))
            while common_depth < max_common and group_stack[common_depth][0] == group_path[common_depth]:
                common_depth += 1
            group_stack = group_stack[:common_depth]

            for segment in group_path[common_depth:]:
                row_order += 10.0
                group_task = GanttTaskDTO(
                    id=str(uuid4()),
                    project_id=project_id,
                    estimate_id=None,
                    parent_id=group_stack[-1][1].id if group_stack else None,
                    name=segment,
                    start_date=start_date,
                    working_days=1,
                    workers_count=None,
                    labor_hours=None,
                    hours_per_day=effective_hours_per_day,
                    is_group=True,
                    type="project",
                    color=color,
                    row_order=row_order,
                )
                tasks.append(group_task)
                group_stack.append((segment, group_task))

            labor_hours = self._calc_labor_hours(est, workers, effective_hours_per_day, effective_fer_hours_by_table_id)
            dur = calculate_working_days(labor_hours, workers, effective_hours_per_day) or 1
            row_order += 10.0

            for _, group_task in group_stack:
                group_task.working_days = max(group_task.working_days, dur)

            tasks.append(GanttTaskDTO(
                id=str(uuid4()),
                project_id=project_id,
                estimate_id=est.id,
                parent_id=group_stack[-1][1].id if group_stack else None,
                name=est.work_name,
                start_date=start_date,
                working_days=dur,
                workers_count=workers,
                labor_hours=labor_hours,
                hours_per_day=effective_hours_per_day,
                is_group=False,
                type="task",
                color=color,
                row_order=row_order,
            ))

        return tasks

    def get_dependencies(self, tasks: list[GanttTaskDTO]) -> list[tuple[str, str]]:
        """Автозависимости после импорта отключены."""
        return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calc_labor_hours(
        self,
        estimate,
        workers: int,
        hours_per_day: float,
        fer_hours_by_table_id: dict[int, float],
    ) -> float:
        """Рассчитывает плановую трудоёмкость задачи в человеко-часах."""
        fer_table_id = getattr(estimate, "fer_table_id", None)
        quantity = getattr(estimate, "quantity", None)
        if fer_table_id is not None and quantity is not None:
            fer_hours = fer_hours_by_table_id.get(int(fer_table_id))
            if fer_hours is not None:
                multiplier = float(getattr(estimate, "fer_multiplier", 1) or 1)
                return round(float(quantity) * fer_hours * multiplier, 2)

        # Из трудоёмкости ЕНиР если есть
        if estimate.labor_hours and estimate.quantity:
            return round(float(estimate.labor_hours) * float(estimate.quantity), 2)

        # По ключевым словам
        name_lower = estimate.work_name.lower()
        for keyword, norm in ENIR_NORMS.items():
            if keyword in name_lower:
                qty   = float(estimate.quantity or 1)
                return round(norm["hours"] * qty, 2)

        # Fallback по стоимости (~50 000 ₽/день бригады)
        if estimate.total_price:
            days = float(estimate.total_price) / 50_000
            return calculate_labor_hours(max(1, min(30, round(days))), workers, hours_per_day)

        return calculate_labor_hours(3, workers, hours_per_day)

    def _estimate_group_path(self, estimate) -> list[str]:
        raw_data = getattr(estimate, "raw_data", None)
        if isinstance(raw_data, dict):
            raw_path = raw_data.get("group_path")
            if isinstance(raw_path, list):
                normalized = [str(item).strip() for item in raw_path if str(item).strip()]
                if normalized:
                    return normalized

        section_name = str(getattr(estimate, "section", "") or "").strip()
        return [section_name or "Прочие работы"]

    def _section_color(self, section: str) -> str:
        lower = section.lower()
        for kw, color in SECTION_COLORS.items():
            if kw in lower:
                return color
        return "#3b82f6"
