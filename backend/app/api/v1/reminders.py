"""待办/日程/提醒接口：CRUD + 标记完成。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import require_permission
from app.models import Reminder, User
from app.services import reminder_service as S
from app.services.audit_service import audited

router = APIRouter(prefix="/reminders", tags=["reminder"])


class ReminderIn(BaseModel):
    title: str
    content: str | None = None
    due_at: int | None = None  # ms 时间戳
    assignee_id: int | None = None
    repeat_cron: str | None = None
    remind_before_minutes: int = 0
    notify_on_due: bool = True


class ReminderUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    due_at: int | None = None
    assignee_id: int | None = None
    status: str | None = None
    repeat_cron: str | None = None
    remind_before_minutes: int | None = None
    notify_on_due: bool | None = None


def _to_out(r: Reminder) -> dict:
    return {
        "id": r.id, "title": r.title, "content": r.content, "due_at": r.due_at,
        "status": r.status, "assignee_id": r.assignee_id, "creator_id": r.creator_id,
        "source": r.source, "repeat_cron": r.repeat_cron,
        "remind_before_minutes": r.remind_before_minutes,
        "notify_on_due": r.notify_on_due, "notified_at": r.notified_at,
        "done_at": r.done_at, "created_at": r.created_at,
    }


@router.get("")
async def list_reminders(
    assignee_id: int | None = Query(None),
    status: str | None = Query(None),
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await S.list_reminders(db, tenant_id=user.tenant_id, assignee_id=assignee_id, status=status)
    return [_to_out(r) for r in rows]


@router.post("")
@audited("reminder.create", "reminder")
async def create_reminder(
    body: ReminderIn,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await S.create_reminder(db, tenant_id=user.tenant_id, creator_id=user.id, data=body.model_dump())
    await db.flush()
    return _to_out(r)


@router.patch("/{rid}")
@audited("reminder.update", "reminder", id_arg="rid")
async def update_reminder(
    rid: int,
    body: ReminderUpdate,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.get(Reminder, rid)
    if not r or r.tenant_id != user.tenant_id:
        raise NotFoundError("待办不存在")
    await S.update_reminder(db, r, body.model_dump(exclude_unset=True))
    await db.flush()
    return _to_out(r)


@router.post("/{rid}/done")
async def done_reminder(
    rid: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.get(Reminder, rid)
    if not r or r.tenant_id != user.tenant_id:
        raise NotFoundError("待办不存在")
    await S.mark_done(db, r)
    await db.flush()
    return _to_out(r)


@router.delete("/{rid}")
@audited("reminder.delete", "reminder", id_arg="rid")
async def delete_reminder(
    rid: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await db.get(Reminder, rid)
    if not r or r.tenant_id != user.tenant_id:
        raise NotFoundError("待办不存在")
    await db.delete(r)
    await db.flush()
    return {"message": "已删除"}
