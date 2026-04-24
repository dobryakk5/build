from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_action
from app.core.permissions import Action
from app.models import GanttTask, ProjectMember, User
from app.models.foreman_task_report import ForemanTaskReport
from app.tasks.foreman_email_tasks import verify_report_token


router = APIRouter(tags=["foreman-reports"])

VALID_STATUSES = {"done_as_planned", "done_not_as_planned", "not_done"}

STATUS_LABELS = {
    "done_as_planned": "Выполнил по плану",
    "done_not_as_planned": "Выполнил не по плану",
    "not_done": "Не выполнил",
    "pending": "Ожидает ответа",
}

STATUS_ICONS = {
    "done_as_planned": "✅",
    "done_not_as_planned": "⚠️",
    "not_done": "❌",
    "pending": "🕐",
}


def _confirmation_html(task_name: str, status: str) -> str:
    label = STATUS_LABELS.get(status, status)
    icon = STATUS_ICONS.get(status, "")
    color = {
        "done_as_planned": "#16a34a",
        "done_not_as_planned": "#d97706",
        "not_done": "#dc2626",
    }.get(status, "#6b7280")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ответ записан</title>
</head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;
             display:flex;align-items:center;justify-content:center;
             min-height:100vh;margin:0;padding:20px;box-sizing:border-box;">
  <div style="background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.1);
              padding:40px 36px;max-width:420px;width:100%;text-align:center;">
    <div style="font-size:48px;margin-bottom:16px;">{icon}</div>
    <h2 style="margin:0 0 10px;color:#1e293b;font-size:20px;">Ответ записан</h2>
    <p style="margin:0 0 20px;color:#64748b;font-size:14px;">
      Задача: <strong>{task_name}</strong>
    </p>
    <div style="background:{color};color:#fff;border-radius:6px;
                padding:12px 20px;font-size:14px;font-weight:600;display:inline-block;">
      {icon} {label}
    </div>
    <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;">
      Ваш ответ сохранен в журнале проекта. Можете закрыть эту страницу.
    </p>
  </div>
</body>
</html>"""


def _already_responded_html(task_name: str, status: str) -> str:
    label = STATUS_LABELS.get(status, status)
    icon = STATUS_ICONS.get(status, "")
    return f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Уже отвечено</title></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;
             display:flex;align-items:center;justify-content:center;
             min-height:100vh;margin:0;padding:20px;box-sizing:border-box;">
  <div style="background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.1);
              padding:40px 36px;max-width:420px;width:100%;text-align:center;">
    <div style="font-size:48px;margin-bottom:16px;">ℹ️</div>
    <h2 style="margin:0 0 10px;color:#1e293b;font-size:20px;">Вы уже ответили</h2>
    <p style="margin:0 0 8px;color:#64748b;font-size:14px;">
      Задача: <strong>{task_name}</strong>
    </p>
    <p style="margin:0;color:#64748b;font-size:14px;">
      Ваш ответ: <strong>{icon} {label}</strong>
    </p>
    <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;">
      Ответ уже записан в журнал. Можете закрыть эту страницу.
    </p>
  </div>
</body>
</html>"""


def _error_html(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Ошибка</title></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;
             display:flex;align-items:center;justify-content:center;
             min-height:100vh;margin:0;padding:20px;box-sizing:border-box;">
  <div style="background:#fff;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.1);
              padding:40px 36px;max-width:420px;width:100%;text-align:center;">
    <div style="font-size:48px;margin-bottom:16px;">⚠️</div>
    <h2 style="margin:0 0 10px;color:#1e293b;font-size:20px;">Ошибка</h2>
    <p style="margin:0;color:#64748b;font-size:14px;">{message}</p>
  </div>
</body>
</html>"""


@router.get(
    "/foreman-reports/{report_id}/respond",
    response_class=HTMLResponse,
    summary="Ответ прораба из письма",
)
async def foreman_respond(
    report_id: str,
    token: str = Query(...),
    status: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if status not in VALID_STATUSES:
        return HTMLResponse(_error_html("Недопустимый статус ответа."), status_code=400)

    if not verify_report_token(token, report_id):
        return HTMLResponse(
            _error_html("Ссылка недействительна или истекла (срок действия 48 часов)."),
            status_code=403,
        )

    report = await db.get(ForemanTaskReport, report_id)
    if not report:
        return HTMLResponse(_error_html("Запись не найдена."), status_code=404)
    if report.token != token:
        return HTMLResponse(_error_html("Ссылка недействительна."), status_code=403)

    task = await db.get(GanttTask, report.task_id)
    task_name = task.name if task else "—"

    if report.status != "pending":
        return HTMLResponse(_already_responded_html(task_name, report.status))

    report.status = status
    report.responded_at = datetime.now(timezone.utc)
    db.add(report)
    await db.commit()

    return HTMLResponse(_confirmation_html(task_name, status))


@router.get(
    "/projects/{project_id}/foreman-reports",
    summary="Список ответов прорабов для журнала",
)
async def list_foreman_reports(
    project_id: str,
    report_date: date | None = Query(
        None,
        description="Конкретная дата YYYY-MM-DD; без параметра возвращаются все записи",
    ),
    member: ProjectMember = Depends(require_action(Action.VIEW)),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if member.role not in {"owner", "pm", "foreman"}:
        raise HTTPException(status_code=403, detail="Нет доступа к ответам прорабов")

    query = (
        select(ForemanTaskReport)
        .where(ForemanTaskReport.project_id == project_id)
        .order_by(ForemanTaskReport.report_date.desc(), ForemanTaskReport.created_at.asc())
    )
    if report_date is not None:
        query = query.where(ForemanTaskReport.report_date == report_date)
    if member.role == "foreman":
        query = query.where(ForemanTaskReport.foreman_id == current_user.id)

    rows = list(await db.scalars(query))
    result = []
    for report in rows:
        foreman_user = await db.get(User, report.foreman_id)
        task = await db.get(GanttTask, report.task_id)
        result.append(
            {
                "id": report.id,
                "report_date": report.report_date.isoformat(),
                "status": report.status,
                "status_label": STATUS_LABELS.get(report.status, report.status),
                "note": report.note,
                "task_id": report.task_id,
                "task_name": task.name if task else None,
                "foreman_id": report.foreman_id,
                "foreman_name": foreman_user.name if foreman_user else None,
                "email_sent_at": report.email_sent_at.isoformat() if report.email_sent_at else None,
                "responded_at": report.responded_at.isoformat() if report.responded_at else None,
            }
        )
    return result
