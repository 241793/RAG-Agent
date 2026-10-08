"""待办/日程/提醒服务：CRUD + 到期扫描推送 + 重复日程重算。"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Reminder

logger = get_logger("reminder")


async def list_reminders(
    db: AsyncSession, *, tenant_id: int, assignee_id: int | None = None,
    status: str | None = None, limit: int = 200,
) -> list[Reminder]:
    q = select(Reminder).where(Reminder.tenant_id == tenant_id)
    if assignee_id is not None:
        q = q.where(Reminder.assignee_id == assignee_id)
    if status:
        q = q.where(Reminder.status == status)
    # 未完成优先 + 按到期时间升序
    q = q.order_by(Reminder.status.asc(), Reminder.due_at.asc().nulls_last()).limit(min(limit, 500))
    return list((await db.execute(q)).scalars().all())


async def create_reminder(db: AsyncSession, *, tenant_id: int, creator_id: int | None, data: dict) -> Reminder:
    r = Reminder(
        tenant_id=tenant_id, title=str(data.get("title") or "未命名")[:256],
        content=data.get("content"), due_at=data.get("due_at"),
        assignee_id=data.get("assignee_id") or creator_id,
        creator_id=creator_id, source=data.get("source") or "manual",
        repeat_cron=data.get("repeat_cron"),
        remind_before_minutes=int(data.get("remind_before_minutes") or 0),
        notify_on_due=bool(data.get("notify_on_due", True)),
    )
    db.add(r)
    await db.flush()
    return r


async def update_reminder(db: AsyncSession, r: Reminder, data: dict) -> Reminder:
    # 仅更新显式传入的字段；due_at/assignee_id 允许传 None 以清空
    for f in ("title", "content", "due_at", "assignee_id", "status", "repeat_cron",
              "remind_before_minutes", "notify_on_due"):
        if f not in data:
            continue
        if data[f] is None and f not in ("due_at", "assignee_id", "content"):
            continue
        setattr(r, f, data[f])
    if data.get("status") == "done":
        r.done_at = int(time.time() * 1000)
    await db.flush()
    return r


async def mark_done(db: AsyncSession, r: Reminder) -> Reminder:
    r.status = "done"
    r.done_at = int(time.time() * 1000)
    await db.flush()
    return r


async def scan_due_reminders(db: AsyncSession, *, now_ms: int | None = None) -> int:
    """扫描到期未提醒的待办，推送通知；重复日程重算下次 due。返回处理条数。"""
    from app.notifiers.base import NotificationMessage
    from app.notifiers.registry import dispatch

    now = now_ms or int(time.time() * 1000)
    rows = (await db.execute(
        select(Reminder).where(
            Reminder.status == "pending",
            Reminder.due_at.is_not(None),
            Reminder.notify_on_due.is_(True),
        )
    )).scalars().all()

    fired = 0
    for r in rows:
        # 触发点：due_at - remind_before_minutes
        trigger_at = (r.due_at or 0) - (r.remind_before_minutes or 0) * 60_000
        if trigger_at > now:
            continue
        # 防重复：本轮已提醒过（notified_at 覆盖不了重复日程，故用"本次 due 是否已提醒"）
        if r.notified_at and r.notified_at >= trigger_at:
            continue

        msg = NotificationMessage(
            title=f"⏰ 待办提醒：{r.title}",
            body=(r.content or "")[:400],
            level="warning", kind="reminder", link="/todo",
            ref_type="reminder", ref_id=r.id, user_id=r.assignee_id,
        )
        try:
            await dispatch(db, tenant_id=r.tenant_id, msg=msg, user_id=r.assignee_id)
        except Exception:  # noqa: BLE001
            logger.exception("reminder_notify_failed", reminder_id=r.id)

        r.notified_at = now
        fired += 1

        # 重复日程：完成后重算下次 due（用 cron 计算）
        if r.repeat_cron:
            try:
                from datetime import datetime, timezone

                from app.services.cron import next_run as cron_next_run

                after = datetime.fromtimestamp((r.due_at or now) / 1000, tz=timezone.utc)
                nxt = cron_next_run(r.repeat_cron, after)
                if nxt:
                    r.due_at = int(nxt.timestamp() * 1000)
                    r.notified_at = None  # 便于下次触发
            except Exception:  # noqa: BLE001
                logger.exception("reminder_reschedule_failed", reminder_id=r.id)

    if fired:
        await db.commit()
    return fired
