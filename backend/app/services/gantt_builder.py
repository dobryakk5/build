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
    ) -> list[GanttTaskDTO]:
        """
        Алгоритм:
        1. Разбиваем строки сметы на последовательные блоки по section
        2. Каждый блок = родительская задача (project), его строки = дочерние
        4. После импорта все группы и задачи стартуют с одной даты
        5. Зависимости оператор проставляет вручную
        """
        tasks: list[GanttTaskDTO] = []

        row_order = 1000.0

        for section_name, section_estimates in self._group_estimates_by_section_run(estimates):
            section_id = str(uuid4())
            color = self._section_color(section_name)
            section_tasks: list[GanttTaskDTO] = []
            max_duration = 1

            for est in section_estimates:
                labor_hours = self._calc_labor_hours(est, workers)
                dur = calculate_working_days(labor_hours, workers, self.HOURS_PER_DAY) or 1
                task_id = str(uuid4())
                row_order += 10.0
                max_duration = max(max_duration, dur)

                section_tasks.append(GanttTaskDTO(
                    id           = task_id,
                    project_id   = project_id,
                    estimate_id  = est.id,
                    parent_id    = section_id,
                    name         = est.work_name,
                    start_date   = start_date,
                    working_days = dur,
                    workers_count = workers,
                    labor_hours  = labor_hours,
                    hours_per_day = self.HOURS_PER_DAY,
                    is_group     = False,
                    type         = "task",
                    color        = color,
                    row_order    = row_order,
                ))
            row_order += 10.0
            section_task = GanttTaskDTO(
                id           = section_id,
                project_id   = project_id,
                estimate_id  = None,
                parent_id    = None,
                name         = section_name,
                start_date   = start_date,
                working_days = max_duration,
                workers_count = None,
                labor_hours  = None,
                hours_per_day = self.HOURS_PER_DAY,
                is_group     = True,
                type         = "project",
                color        = color,
                row_order    = row_order - len(section_estimates) * 10.0 - 5.0,
            )
            tasks.append(section_task)
            tasks.extend(section_tasks)

        return tasks

    def get_dependencies(self, tasks: list[GanttTaskDTO]) -> list[tuple[str, str]]:
        """Автозависимости после импорта отключены."""
        return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calc_labor_hours(self, estimate, workers: int) -> float:
        """Рассчитывает плановую трудоёмкость задачи в человеко-часах."""
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
            return calculate_labor_hours(max(1, min(30, round(days))), workers, self.HOURS_PER_DAY)

        return calculate_labor_hours(3, workers, self.HOURS_PER_DAY)

    def _group_estimates_by_section_run(self, estimates: list) -> list[tuple[str, list]]:
        ordered_estimates = sorted(
            estimates,
            key=lambda est: (
                getattr(est, "row_order", 0),
                getattr(est, "created_at", None) or "",
                getattr(est, "id", ""),
            ),
        )

        groups: list[tuple[str, list]] = []
        current_name: str | None = None
        current_items: list = []

        for est in ordered_estimates:
            section_name = (str(getattr(est, "section", "") or "").strip() or "Прочие работы")
            if current_name != section_name:
                if current_items:
                    groups.append((current_name or "Прочие работы", current_items))
                current_name = section_name
                current_items = [est]
                continue
            current_items.append(est)

        if current_items:
            groups.append((current_name or "Прочие работы", current_items))

        return groups

    def _section_color(self, section: str) -> str:
        lower = section.lower()
        for kw, color in SECTION_COLORS.items():
            if kw in lower:
                return color
        return "#3b82f6"
