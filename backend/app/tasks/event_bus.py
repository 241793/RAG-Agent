"""进程内事件总线：极简发布订阅，用于「文档入库完成」等事件触发定时任务。

设计：发布事件时查该租户中 trigger_kind=event 且 event_name 匹配的启用任务，
把它们投递为一次性执行（不改变其 next_run_at）。派发用 asyncio.create_task，
不阻塞发布方。带简单的同任务去抖（避免批量入库触发同一任务 N 次）。
"""
from __future__ import annotations

import asyncio
import time

from app.core.logging import get_logger

logger = get_logger("event_bus")

# 去抖：task_id → 最近触发时刻（ms）
_DEBOUNCE: dict[int, int] = {}
_DEBOUNCE_MS = 2000


async def publish(event_name: str, *, tenant_id: int, payload: dict | None = None) -> int:
    """发布事件，返回派发的任务数。"""
    from sqlalchemy import select

    from app.core.db import AsyncSessionLocal
    from app.models import ScheduledTask
    from app.tasks.scheduler_tasks import execute_task

    dispatched = 0
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(ScheduledTask).where(
                        ScheduledTask.tenant_id == tenant_id,
                        ScheduledTask.enabled.is_(True),
                        ScheduledTask.trigger_kind == "event",
                        ScheduledTask.event_name == event_name,
                    )
                )
            ).scalars().all()
            now = int(time.time() * 1000)
            for t in rows:
                last = _DEBOUNCE.get(t.id, 0)
                if now - last < _DEBOUNCE_MS:
                    continue
                _DEBOUNCE[t.id] = now
                # 事件载荷注入到任务输入，供工作流/提示词使用
                if payload:
                    t.inputs = {**(t.inputs or {}), "_event": event_name, **payload}
                    db.add(t)
                dispatched += 1
                asyncio.create_task(execute_task(t.id))
            if dispatched:
                await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("event_publish_error", event_name=event_name)
    if dispatched:
        logger.info("event_dispatched", event_name=event_name, count=dispatched)

    # 出站：把事件推给订阅方（外部系统集成）。异步、失败不阻断。
    try:
        from app.services.event_subscription_service import dispatch_event

        await dispatch_event(event_name, tenant_id=tenant_id, payload=payload)
    except Exception:  # noqa: BLE001
        logger.exception("event_outbound_failed", event_name=event_name)

    return dispatched
