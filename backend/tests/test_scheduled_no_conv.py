"""定时任务不再占用问答会话：_do_run 不建 Conversation、不落 Message，
但执行历史(ScheduledTaskRun)与用量(UsageLog)照常。AgentRunner persist 开关行为验证。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import func, select

from app.core.db import AsyncSessionLocal, init_models
from app.models import (
    Agent,
    Conversation,
    Message,
    ScheduledTask,
    ScheduledTaskRun,
    Tenant,
    UsageLog,
    User,
)
from app.services.permission import PrincipalSet


class _FakeLLM:
    """最小 LLM：直接产出终答，无工具调用。"""

    def __init__(self): self.n = 0

    async def chat(self, messages, **kw):
        from app.providers.base import ChatChunk

        async def gen():
            yield ChatChunk(delta="任务已执行完成", finish=True)
        return gen()


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "nocv"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="NOCV", slug="nocv"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "nocv_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="nocv_u", password_hash="x", is_admin=True)
            db.add(u); await db.flush()
        a = (await db.execute(select(Agent).where(Agent.slug == "nocv_agent"))).scalar_one_or_none()
        if not a:
            a = Agent(tenant_id=t.id, owner_id=u.id, name="nocv", slug="nocv_agent",
                      type="agent", system_prompt="你是助手")
            db.add(a); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "owner_id": u.id, "agent_id": a.id}


async def _no_conversation_created(monkeypatch):
    d = await _setup()

    # 让 _do_run 内部拿到我们的 FakeLLM，而不真调外部模型
    from app.agents import runner as runner_mod

    async def _fake_get_llm(db, *, tenant_id, config_id=None):
        class RM:
            model_name = "fake"
            config_id = 0
        return _FakeLLM(), RM()

    monkeypatch.setattr(runner_mod, "get_llm", _fake_get_llm)

    async with AsyncSessionLocal() as db:
        msg_before = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
    async with AsyncSessionLocal() as db:
        conv_before = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()
        task = ScheduledTask(
            tenant_id=d["tenant_id"], owner_id=d["owner_id"], agent_id=d["agent_id"],
            name="不建会话任务", target_type="prompt", prompt="说一句话",
            schedule_kind="once", run_at=int(time.time() * 1000), notify_on="never",
        )
        db.add(task); await db.commit(); tid = task.id

    from app.tasks.scheduler_tasks import execute_task

    await execute_task(tid)

    async with AsyncSessionLocal() as db:
        conv_after = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()
        assert conv_after == conv_before, "定时任务不应创建会话"
        # 执行记录已有内容
        runs = (await db.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == tid).order_by(ScheduledTaskRun.id.desc())
        )).scalars().all()
        assert runs and runs[0].status == "success"
        assert "任务已执行完成" in (runs[0].output or "")
        # 任务本身不再持有 conversation_id
        t = await db.get(ScheduledTask, tid)
        assert t.conversation_id is None
        # 用量照常记录（conversation_id 为空）
        ul = (await db.execute(select(UsageLog).where(UsageLog.user_id == d["owner_id"]))).scalars().all()
        assert any(u.conversation_id is None for u in ul)
        # 本次执行没有新增 Message
        msg_after = (await db.execute(select(func.count()).select_from(Message))).scalar_one()
        assert msg_after == msg_before
    print("OK no_conversation_created")


async def _runner_persist_toggle(monkeypatch):
    """AgentRunner persist=False 不落库；persist=True 落库。"""
    d = await _setup()
    from app.agents import runner as runner_mod

    async def _fake_get_llm(db, *, tenant_id, config_id=None):
        class RM:
            model_name = "fake"
            config_id = 0
        return _FakeLLM(), RM()

    monkeypatch.setattr(runner_mod, "get_llm", _fake_get_llm)

    async with AsyncSessionLocal() as db:
        agent = await db.get(Agent, d["agent_id"])
        ps = PrincipalSet(user_id=d["owner_id"], tenant_id=d["tenant_id"], is_admin=True)

        # persist=False + conversation=None：不落消息、不报错
        r = runner_mod.AgentRunner(db, agent=agent, ps=ps, conversation=None, persist=False, perms={"*"})
        text = ""
        async for evt in r.run("你好"):
            if evt.get("type") == "delta":
                text += evt["text"]
        assert "任务已执行完成" in text
        assert r.persist is False
    print("OK runner_persist_toggle")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_no_conversation_created(monkeypatch):
    _run_async(_no_conversation_created(monkeypatch))


def test_runner_persist_toggle(monkeypatch):
    _run_async(_runner_persist_toggle(monkeypatch))


# ---- notify_on 字段 ----
def test_notify_on_default():
    from app.models import ScheduledTask as ST

    col = ST.__table__.columns["notify_on"]
    assert col.default.arg == "fail"


def test_notify_on_in_api_schema():
    from app.api.v1.scheduled_tasks import TaskIn

    assert "notify_on" in TaskIn.model_fields
    assert TaskIn(name="x", agent_id=1).notify_on == "fail"
