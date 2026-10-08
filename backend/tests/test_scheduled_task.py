"""定时任务模型 + cron 下次运行计算测试。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.models import Agent, ScheduledTask, Tenant, User


async def _run():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "st"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="ST", slug="st"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "st_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="st_u", password_hash="x"); db.add(u); await db.flush()
        a = (await db.execute(select(Agent).where(Agent.slug == "st_agent"))).scalar_one_or_none()
        if not a:
            a = Agent(tenant_id=t.id, owner_id=u.id, name="st", slug="st_agent", type="agent"); db.add(a); await db.flush()
        await db.commit()
        tid, uid, aid = t.id, u.id, a.id

    async with AsyncSessionLocal() as db:
        from app.api.v1.scheduled_tasks import _compute_next

        task = ScheduledTask(
            tenant_id=tid, owner_id=uid, agent_id=aid, name="每日早报",
            target_type="prompt", prompt="总结昨天", schedule_kind="cron", cron_expr="0 9 * * *",
        )
        nxt = await _compute_next(task)
        assert nxt > int(time.time() * 1000)
        db.add(task); await db.commit()
        sid = task.id

    async with AsyncSessionLocal() as db:
        row = await db.get(ScheduledTask, sid)
        assert row.name == "每日早报" and row.enabled is True
        # interval 计算
        from app.api.v1.scheduled_tasks import _compute_next

        row.schedule_kind = "interval"; row.interval_seconds = 3600
        nxt2 = await _compute_next(row)
        assert nxt2 > int(time.time() * 1000)
    print("OK scheduled_task")


def test_scheduled_task_model():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.set_event_loop(None)
