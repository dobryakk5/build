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
    },
    "viewer": {
        Action.VIEW,
    },
}


def can(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(role, set())
