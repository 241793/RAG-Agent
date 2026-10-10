"""定时任务接口：CRUD + 启停 + 立即运行 + 运行信息。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import Agent, ScheduledTask, User
from app.services.audit_service import audited

router = APIRouter(prefix="/scheduled-tasks", tags=["schedule"])


class TaskIn(BaseModel):
    name: str
    agent_id: int
    target_type: str = "prompt"  # prompt | workflow
    prompt: str | None = None
    inputs: dict | None = None
    schedule_kind: str = "cron"  # cron | interval | once
    cron_expr: str | None = None
    interval_seconds: int | None = None
    run_at: int | None = None  # once 用（ms 时间戳）
    delay_seconds: int | None = None  # 便捷：相对当前时间（秒）→ 自动转 once
    trigger_kind: str = "schedule"  # schedule | event
    event_name: str | None = None
    notify_on: str = "fail"  # always | success | fail | never
    max_retries: int = 0
    retry_interval_seconds: int = 60
    timeout_seconds: int | None = None
    enabled: bool = True
    depends_on_task_id: int | None = None  # 前置任务：本任务在它成功后自动触发（A→B）
    room_id: int | None = None  # 结果推送目标群（群管机器人）
    room_bot_agent_id: int | None = None  # 群内发言机器人身份（留空=agent_id）


def _to_out(t: ScheduledTask) -> dict:
    return {
        "id": t.id, "name": t.name, "agent_id": t.agent_id, "target_type": t.target_type,
        "prompt": t.prompt, "inputs": t.inputs,
        "schedule_kind": t.schedule_kind, "cron_expr": t.cron_expr,
        "interval_seconds": t.interval_seconds, "run_at": t.run_at,
        "trigger_kind": t.trigger_kind, "event_name": t.event_name,
        "notify_on": t.notify_on,
        "max_retries": t.max_retries, "retry_count": t.retry_count,
        "retry_interval_seconds": t.retry_interval_seconds, "timeout_seconds": t.timeout_seconds,
        "enabled": t.enabled,
        "depends_on_task_id": t.depends_on_task_id,
        "room_id": t.room_id, "room_bot_agent_id": t.room_bot_agent_id,
        "next_run_at": t.next_run_at, "last_run_at": t.last_run_at,
        "last_status": t.last_status, "last_result": t.last_result,
        "last_run_id": t.last_run_id, "conversation_id": t.conversation_id, "run_count": t.run_count,
    }


async def _compute_next(task: ScheduledTask) -> int | None:
    from app.services.schedule_service import compute_next

    return compute_next(task)


def _validate_schedule(body: TaskIn) -> None:
    from app.services.schedule_service import validate_schedule

    validate_schedule(body.model_dump())


@router.get("")
async def list_tasks(
    user: User = Depends(require_permission("schedule:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (await db.execute(
        select(ScheduledTask).where(ScheduledTask.tenant_id == user.tenant_id).order_by(ScheduledTask.id.desc())
    )).scalars().all()
    return [_to_out(t) for t in rows]


async def _get(db: AsyncSession, task_id: int, tenant_id: int) -> ScheduledTask:
    t = await db.get(ScheduledTask, task_id)
    if not t or t.tenant_id != tenant_id:
        raise NotFoundError("定时任务不存在")
    return t


@router.post("")
@audited("scheduled_task.create", "scheduled_task")
async def create_task(
    body: TaskIn,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_schedule(body)
    agent = await db.get(Agent, body.agent_id)
    if not agent or agent.tenant_id != user.tenant_id:
        raise NotFoundError("目标智能体不存在")
    from app.services.schedule_service import create_task as _svc_create

    t = await _svc_create(db, tenant_id=user.tenant_id, owner_id=user.id, data=body.model_dump())
    return _to_out(t)


@router.patch("/{task_id}")
@audited("scheduled_task.update", "scheduled_task", id_arg="task_id")
async def update_task(
    task_id: int,
    body: TaskIn,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.schedule_service import update_task as _svc_update

    _validate_schedule(body)
    t = await _get(db, task_id, user.tenant_id)
    await _svc_update(db, t, body.model_dump())
    return _to_out(t)


@router.post("/{task_id}/enable")
async def set_enabled(
    task_id: int,
    body: dict,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await _get(db, task_id, user.tenant_id)
    t.enabled = bool(body.get("enabled", True))
    if t.enabled:
        t.next_run_at = await _compute_next(t)
    await db.flush()
    return {"enabled": t.enabled}


@router.post("/{task_id}/run-now")
async def run_now(
    task_id: int,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    import asyncio

    from app.tasks.scheduler_tasks import execute_task

    t = await _get(db, task_id, user.tenant_id)
    asyncio.create_task(execute_task(t.id, manual=True))
    return {"message": "已触发执行"}


@router.delete("/{task_id}")
@audited("scheduled_task.delete", "scheduled_task", id_arg="task_id")
async def delete_task(
    task_id: int,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await _get(db, task_id, user.tenant_id)
    # 级联清理执行历史
    from sqlalchemy import delete as sql_delete

    from app.models import ScheduledTaskRun

    await db.execute(sql_delete(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id))
    await db.delete(t)
    await db.flush()
    return {"message": "已删除"}


@router.get("/{task_id}/runs")
async def list_runs(
    task_id: int,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(require_permission("schedule:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    from app.models import ScheduledTaskRun

    await _get(db, task_id, user.tenant_id)  # 校验归属
    base = select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(base.order_by(ScheduledTaskRun.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id, "status": r.status, "attempt": r.attempt,
                "started_at": r.started_at, "finished_at": r.finished_at, "duration_ms": r.duration_ms,
                "output": r.output, "error": r.error, "workflow_run_id": r.workflow_run_id,
            }
            for r in rows
        ],
    }
