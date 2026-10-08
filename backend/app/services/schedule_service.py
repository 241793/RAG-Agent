"""定时任务业务逻辑：校验、算下次运行时间、创建/更新。

供 API（api/v1/scheduled_tasks.py）与 AI 工具（platform_tools）共享，保证行为一致。
"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models import Agent, ScheduledTask
from app.services.cron import next_run as cron_next_run
from app.services.cron import parse_cron


def compute_next(task: ScheduledTask, after_ms: int | None = None) -> int | None:
    """算下次运行时刻（ms）。event 由调用方置 None；once 用 run_at。

    after_ms：递推基准（毫秒）。默认从"现在"算；传入上次计划时刻可让 cron 按时区
    正确递推（用于错过补跑 catch-up）。
    """
    from datetime import timezone

    tz_name = getattr(task, "timezone", None) or "Asia/Shanghai"
    if task.schedule_kind == "once":
        return int(task.run_at) if task.run_at else None
    if task.schedule_kind == "interval" and task.interval_seconds:
        base = after_ms if after_ms is not None else int(time.time() * 1000)
        return int(base) + int(task.interval_seconds) * 1000
    after = datetime.fromtimestamp(after_ms / 1000, tz=timezone.utc) if after_ms is not None else None
    dt = cron_next_run(task.cron_expr or "0 9 * * *", after, tz_name=tz_name)
    return int(dt.timestamp() * 1000)


def validate_schedule(data: dict) -> None:
    """按字段字典校验调度配置。抛 ValidationError。"""
    from app.core.config import settings

    kind = data.get("schedule_kind") or "cron"
    if kind == "cron":
        if not data.get("cron_expr"):
            raise ValidationError("请提供 cron 表达式")
        try:
            parse_cron(data["cron_expr"])  # 抛错即非法
        except ValueError as e:
            raise ValidationError(f"cron 表达式非法：{e}") from e
    elif kind == "interval":
        iv = data.get("interval_seconds")
        if not iv or int(iv) < 60:
            raise ValidationError("间隔至少 60 秒")
    elif kind == "once":
        if not data.get("run_at"):
            raise ValidationError("一次性任务需要提供 run_at")
    else:
        raise ValidationError("schedule_kind 只能为 cron/interval/once")
    mr = int(data.get("max_retries") or 0)
    if mr > settings.scheduler_max_retries_cap:
        raise ValidationError(f"重试次数不能超过 {settings.scheduler_max_retries_cap}")


async def create_task(
    db: AsyncSession, *, tenant_id: int, owner_id: int, data: dict
) -> ScheduledTask:
    """创建定时任务。data 字段：name/agent_id/target_type/prompt/inputs/schedule_kind/
    cron_expr/interval_seconds/run_at/delay_seconds/trigger_kind/event_name/max_retries/
    retry_interval_seconds/timeout_seconds/enabled。

    delay_seconds：便捷相对时间 → 自动转成 once（"X 分钟后提醒"）。
    """
    data = dict(data)
    # 便捷：delay_seconds → once + run_at
    if data.get("delay_seconds") and not data.get("run_at"):
        data["schedule_kind"] = "once"
        data["run_at"] = int(time.time() * 1000) + int(data["delay_seconds"]) * 1000
    if not data.get("schedule_kind"):
        data["schedule_kind"] = "cron"
    validate_schedule(data)

    agent = await db.get(Agent, int(data.get("agent_id") or 0))
    if not agent or agent.tenant_id != tenant_id:
        raise NotFoundError("目标智能体不存在")

    t = ScheduledTask(
        tenant_id=tenant_id, owner_id=owner_id, agent_id=agent.id,
        name=str(data.get("name") or "未命名任务"),
        enabled=bool(data.get("enabled", True)),
        target_type=data.get("target_type") or "prompt",
        prompt=data.get("prompt"), inputs=data.get("inputs"),
        schedule_kind=data.get("schedule_kind"), cron_expr=data.get("cron_expr"),
        interval_seconds=data.get("interval_seconds"), run_at=data.get("run_at"),
        trigger_kind=data.get("trigger_kind") or "schedule",
        event_name=data.get("event_name"),
        notify_on=data.get("notify_on") or "fail",
        max_retries=int(data.get("max_retries") or 0),
        retry_interval_seconds=int(data.get("retry_interval_seconds") or 60),
        timeout_seconds=data.get("timeout_seconds"),
        depends_on_task_id=data.get("depends_on_task_id"),
    )
    if t.depends_on_task_id:
        await _validate_dep_chain(db, tenant_id, t.id, t.depends_on_task_id)
    # 有依赖的任务不参与定时扫描（next_run_at=None），仅由前置任务成功后触发
    t.next_run_at = None if (t.trigger_kind == "event" or t.depends_on_task_id) else compute_next(t)
    db.add(t)
    await db.flush()
    return t


async def _validate_dep_chain(db: AsyncSession, tenant_id: int, self_id: int | None, dep_id: int) -> None:
    """校验依赖链：前置任务存在且同租户、不构成环、不自依赖。"""
    from app.models import ScheduledTask

    if self_id is not None and dep_id == self_id:
        raise ValidationError("任务不能依赖自身")
    seen: set[int] = set()
    cur: int | None = dep_id
    while cur is not None:
        if self_id is not None and cur == self_id:
            raise ValidationError("依赖链构成环")
        if cur in seen:
            raise ValidationError("依赖链构成环")
        seen.add(cur)
        row = await db.get(ScheduledTask, cur)
        if not row or row.tenant_id != tenant_id:
            raise ValidationError("前置任务不存在")
        cur = row.depends_on_task_id
        if len(seen) > 100:
            raise ValidationError("依赖链过长")


async def update_task(db: AsyncSession, task: ScheduledTask, data: dict) -> ScheduledTask:
    data = dict(data)
    if data.get("delay_seconds") and not data.get("run_at"):
        data["schedule_kind"] = "once"
        data["run_at"] = int(time.time() * 1000) + int(data["delay_seconds"]) * 1000
    validate_schedule(data)
    if "depends_on_task_id" in data:
        dep = data.get("depends_on_task_id")
        if dep:
            await _validate_dep_chain(db, task.tenant_id, task.id, int(dep))
        task.depends_on_task_id = dep
    for f in ("name", "agent_id", "target_type", "prompt", "inputs", "schedule_kind",
              "cron_expr", "interval_seconds", "run_at", "trigger_kind", "event_name",
              "notify_on", "max_retries", "retry_interval_seconds", "timeout_seconds", "enabled"):
        if data.get(f) is not None:
            setattr(task, f, data[f])
    task.retry_count = 0
    task.next_run_at = None if (task.trigger_kind == "event" or task.depends_on_task_id) else compute_next(task)
    await db.flush()
    return task
