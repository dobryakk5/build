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

from app.core.date_utils import add_working_days


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
    is_group:    bool
    type:        str       # task | project
    color:       str
    row_order:   float = field(default=1000.0)


# ── Builder ───────────────────────────────────────────────────────────────────

class GanttBuilder:
    HOURS_PER_DAY = 8

    def build(
        self,
        project_id: str,
        estimates:  list,       # list[Estimate ORM objects]
        start_date: date,
        workers:    int = 3,
    ) -> list[GanttTaskDTO]:
        """
        Алгоритм:
        1. Группируем строки сметы по разделам (section)
        2. Сортируем разделы по технологической последовательности
        3. Каждый раздел = родительская задача (project), его строки = дочерние
        4. Раздел начинается после окончания предыдущего
        5. Внутри раздела задачи идут последовательно
        """
        tasks: list[GanttTaskDTO] = []
        self._dep_pairs: list[tuple[str, str]] = []

        # Группируем по разделам
        sections: dict[str, list] = {}
        for est in estimates:
            sec = est.section or "Прочие работы"
            sections.setdefault(sec, []).append(est)

        # Сортируем разделы
        sorted_sections = self._sort_sections(list(sections.keys()))

        current_start = start_date
        prev_section_id: str | None = None
        row_order = 1000.0

        for section_name in sorted_sections:
            section_estimates = sections[section_name]
            section_id = str(uuid4())
            color = self._section_color(section_name)

            # Дочерние задачи
            section_end = current_start
            task_start  = current_start

            for est in section_estimates:
                dur = self._calc_days(est, workers)
                task_id = str(uuid4())
                row_order += 10.0

                tasks.append(GanttTaskDTO(
                    id           = task_id,
                    project_id   = project_id,
                    estimate_id  = est.id,
                    parent_id    = section_id,
                    name         = est.work_name,
                    start_date   = task_start,
                    working_days = dur,
                    workers_count = workers,
                    is_group     = False,
                    type         = "task",
                    color        = color,
                    row_order    = row_order,
                ))

                task_end = add_working_days(task_start, dur)
                if task_end > section_end:
                    section_end = task_end
                task_start = task_end

            # Родительская задача
            total_days = max(1, sum(
                self._calc_days(e, workers) for e in section_estimates
            ))
            row_order += 10.0
            section_task = GanttTaskDTO(
                id           = section_id,
                project_id   = project_id,
                estimate_id  = None,
                parent_id    = None,
                name         = section_name,
                start_date   = current_start,
                working_days = total_days,
                workers_count = None,
                is_group     = True,
                type         = "project",
                color        = color,
                row_order    = row_order - total_days * 10.0 - 5.0,
            )

            # Зависимость: этот раздел идёт после предыдущего
            if prev_section_id:
                self._dep_pairs.append((section_id, prev_section_id))

            tasks.insert(
                next((i for i, t in enumerate(tasks) if t.parent_id == section_id), len(tasks)) - len(section_estimates),
                section_task,
            )

            prev_section_id = section_id
            current_start   = section_end

        return tasks

    def get_dependencies(self, tasks: list[GanttTaskDTO]) -> list[tuple[str, str]]:
        """Возвращает пары (task_id, depends_on_id) для сохранения в task_dependencies."""
        return self._dep_pairs

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _calc_days(self, estimate, workers: int) -> int:
        """Рассчитывает длительность в рабочих днях."""
        # Из трудоёмкости ЕНиР если есть
        if estimate.labor_hours and estimate.quantity:
            hours = float(estimate.labor_hours) * float(estimate.quantity)
            days  = hours / (self.HOURS_PER_DAY * workers)
            return max(1, round(days))

        # По ключевым словам
        name_lower = estimate.work_name.lower()
        for keyword, norm in ENIR_NORMS.items():
            if keyword in name_lower:
                qty   = float(estimate.quantity or 1)
                hours = norm["hours"] * qty
                days  = hours / (self.HOURS_PER_DAY * workers)
                return max(1, round(days))

        # Fallback по стоимости (~50 000 ₽/день бригады)
        if estimate.total_price:
            days = float(estimate.total_price) / 50_000
            return max(1, min(30, round(days)))

        return 3

    def _sort_sections(self, sections: list[str]) -> list[str]:
        def key(name: str) -> int:
            lower = name.lower()
            for i, kw in enumerate(SECTION_ORDER):
                if kw in lower:
                    return i
            return len(SECTION_ORDER)
        return sorted(sections, key=key)

    def _section_color(self, section: str) -> str:
        lower = section.lower()
        for kw, color in SECTION_COLORS.items():
            if kw in lower:
                return color
        return "#3b82f6"
