# backend/app/core/permissions.py
from enum import Enum


class Action(str, Enum):
    VIEW             = "view"
    EDIT             = "edit"
    DELETE           = "delete"
    COMMENT          = "comment"
    EDIT_PROGRESS    = "edit_progress"   # только через отчёт для foreman
    MANAGE_USERS     = "manage_users"
    MANAGE_PROJECTS  = "manage_projects"
    SUBMIT_REPORT    = "submit_report"
    VIEW_REPORTS     = "view_reports"
    REPORT_DELAY     = "report_delay"


REVALIDATE_BLOCKED_BATCH_PERMISSION = "estimate_batch.revalidate_blocked"


ROLE_PERMISSIONS: dict[str, set[Action]] = {
    "owner": {
        Action.VIEW, Action.EDIT, Action.DELETE, Action.COMMENT,
        Action.EDIT_PROGRESS, Action.MANAGE_USERS, Action.MANAGE_PROJECTS,
        Action.SUBMIT_REPORT, Action.VIEW_REPORTS,
    },
    "pm": {
        Action.VIEW, Action.EDIT, Action.COMMENT,
        Action.EDIT_PROGRESS, Action.MANAGE_PROJECTS,
        Action.VIEW_REPORTS,
    },
    "foreman": {
        Action.VIEW, Action.COMMENT,
        Action.SUBMIT_REPORT,
        # EDIT_PROGRESS намеренно отсутствует — только через отчёт
    },
    "supplier": {
        Action.VIEW, Action.COMMENT,
        Action.REPORT_DELAY,
    },
    "viewer": {
        Action.VIEW,
    },
}


def can(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(role, set())


def project_permission_codes(role: str) -> set[str]:
    if role in {"owner", "pm"}:
        return {REVALIDATE_BLOCKED_BATCH_PERMISSION}
    return set()


def has_project_permission(role: str, permission_code: str) -> bool:
    return permission_code in project_permission_codes(role)
