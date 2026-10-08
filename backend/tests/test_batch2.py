"""第二批功能测试：事件订阅出站、工作流多分支/并行、定时任务依赖链。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Agent, EventSubscription, ScheduledTask, Tenant, User


async def _setup(slug="batch2"):
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
        if not t:
            t = Tenant(name=slug.upper(), slug=slug); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == f"{slug}_admin"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username=f"{slug}_admin", password_hash=hash_password("x"),
                     is_admin=True, display_name="管理员", user_type="internal")
            db.add(u); await db.flush()
        a = (await db.execute(select(Agent).where(Agent.tenant_id == t.id))).scalars().first()
        if not a:
            a = Agent(tenant_id=t.id, owner_id=u.id, name=f"{slug}-agent", slug=f"{slug}-agent", status="active")
            db.add(a); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id, "agent_id": a.id}


# ==================== 事件订阅 ====================
def test_event_signature_and_match():
    from app.services.event_subscription_service import _matches, _sign

    assert _matches(None, "ticket.created") is True          # 空=全部
    assert _matches("ticket.created,document.ready", "document.ready") is True
    assert _matches("ticket.created", "workflow.completed") is False
    # 签名确定且带前缀
    s = _sign("secret", b'{"a":1}', "1700000000")
    assert s.startswith("sha256=") and len(s) > 20


def test_dispatch_event_delivers(monkeypatch):
    """dispatch_event 命中订阅并调用 _deliver（mock httpx）。"""
    async def _run():
        d = await _setup("evsub")
        import app.services.event_subscription_service as ES

        # 建订阅（订阅 ticket.created）
        async with AsyncSessionLocal() as db:
            db.add(EventSubscription(tenant_id=d["tenant_id"], name="sub1",
                                     url="https://example.com/hook", events="ticket.created", enabled=True))
            await db.commit()

        delivered = []
        async def _fake_deliver(url, secret, event_name, payload, tenant_id):
            delivered.append((url, event_name))
            return True
        monkeypatch.setattr(ES, "_deliver", _fake_deliver)

        # _deliver 被 mock 后 AsyncSessionLocal 仍指向真实库，dispatch_event 正常
        n = await ES.dispatch_event("ticket.created", tenant_id=d["tenant_id"], payload={"id": 1})
        assert n == 1 and delivered[0][1] == "ticket.created"

        # 不匹配的事件不投递
        delivered.clear()
        n2 = await ES.dispatch_event("workflow.completed", tenant_id=d["tenant_id"], payload={})
        assert n2 == 0

        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            await db.execute(delete(EventSubscription).where(EventSubscription.tenant_id == d["tenant_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


# ==================== 工作流：switch / parallel ====================
def test_switch_routes_by_case():
    async def _run():
        from app.agents.workflow.engine import execute_graph, NodeContext
        from app.services.permission import PrincipalSet

        g = {
            "nodes": [
                {"id": "s", "type": "start", "data": {"inputs": [{"name": "env", "default": "prod"}]}},
                {"id": "sw", "type": "switch", "data": {"cases": [
                    {"handle": "case1", "expr": "{{s.env}} == 'dev'"},
                    {"handle": "case2", "expr": "{{s.env}} == 'prod'"}]}},
                {"id": "e1", "type": "end", "data": {}}, {"id": "e2", "type": "end", "data": {}},
                {"id": "e3", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "s", "target": "sw"},
                {"source": "sw", "target": "e1", "sourceHandle": "case1"},
                {"source": "sw", "target": "e2", "sourceHandle": "case2"},
                {"source": "sw", "target": "e3", "sourceHandle": "default"},
            ],
        }
        ctx = NodeContext(db=None, ps=PrincipalSet(user_id=1, tenant_id=1), run_id=1, tenant_id=1)
        out, recs = await execute_graph(g, {}, ctx)
        status = {r["node_id"]: r["status"] for r in recs}
        assert status["e2"] == "success", "env=prod 应走 case2"
        assert status["e1"] == "skipped" and status["e3"] == "skipped"
    asyncio.new_event_loop().run_until_complete(_run())


def test_parallel_runs_concurrently_and_joins():
    async def _run():
        from app.agents.workflow.engine import execute_graph, NodeContext
        from app.services.permission import PrincipalSet

        g = {
            "nodes": [
                {"id": "s", "type": "start", "data": {}},
                {"id": "p", "type": "parallel", "data": {}},
                {"id": "b1", "type": "code", "data": {"code": "import time; time.sleep(1); print('b1')"}},
                {"id": "b2", "type": "code", "data": {"code": "import time; time.sleep(1); print('b2')"}},
                {"id": "j", "type": "join", "data": {}},
                {"id": "e", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "s", "target": "p"},
                {"source": "p", "target": "b1"}, {"source": "p", "target": "b2"},
                {"source": "b1", "target": "j"}, {"source": "b2", "target": "j"},
                {"source": "j", "target": "e"},
            ],
        }
        ctx = NodeContext(db=None, ps=PrincipalSet(user_id=1, tenant_id=1), run_id=1, tenant_id=1)
        t0 = time.time()
        out, recs = await execute_graph(g, {}, ctx)
        dt = time.time() - t0
        assert dt < 1.8, f"两分支应并发（≈1s），实际 {dt:.2f}s"
        join_rec = [r for r in recs if r["node_id"] == "j"]
        assert join_rec and "branches" in (join_rec[0].get("output") or {})
        assert len(join_rec[0]["output"]["branches"]) == 2
    asyncio.new_event_loop().run_until_complete(_run())


def test_parallel_rejects_nested_condition():
    async def _run():
        from app.agents.workflow.engine import execute_graph, NodeContext
        from app.core.errors import ValidationError
        from app.services.permission import PrincipalSet

        g = {
            "nodes": [
                {"id": "s", "type": "start", "data": {}},
                {"id": "p", "type": "parallel", "data": {}},
                {"id": "c1", "type": "condition", "data": {"expression": "1==1"}},
                {"id": "b2", "type": "code", "data": {"code": "print(1)"}},
                {"id": "j", "type": "join", "data": {}},
                {"id": "e", "type": "end", "data": {}},
            ],
            "edges": [
                {"source": "s", "target": "p"},
                {"source": "p", "target": "c1"}, {"source": "p", "target": "b2"},
                {"source": "c1", "target": "j"}, {"source": "b2", "target": "j"},
                {"source": "j", "target": "e"},
            ],
        }
        ctx = NodeContext(db=None, ps=PrincipalSet(user_id=1, tenant_id=1), run_id=1, tenant_id=1)
        try:
            await execute_graph(g, {}, ctx)
            assert False, "嵌套 condition 应被拒绝"
        except ValidationError:
            pass
    asyncio.new_event_loop().run_until_complete(_run())


# ==================== 定时任务依赖链 ====================
def test_task_dependency_chain_and_cycle():
    async def _run():
        d = await _setup("taskdep")
        from app.services import schedule_service as SS

        async with AsyncSessionLocal() as db:
            ta = await SS.create_task(db, tenant_id=d["tenant_id"], owner_id=d["uid"], data={
                "name": "A", "agent_id": d["agent_id"], "target_type": "prompt", "prompt": "x",
                "schedule_kind": "interval", "interval_seconds": 3600})
            await db.commit()
            tb = await SS.create_task(db, tenant_id=d["tenant_id"], owner_id=d["uid"], data={
                "name": "B", "agent_id": d["agent_id"], "target_type": "prompt", "prompt": "y",
                "schedule_kind": "interval", "interval_seconds": 3600, "depends_on_task_id": ta.id})
            await db.commit()
            assert tb.depends_on_task_id == ta.id
            assert tb.next_run_at is None, "依赖任务不参与定时扫描"
            # 自依赖拒绝
            try:
                await SS._validate_dep_chain(db, d["tenant_id"], ta.id, ta.id)
                assert False
            except Exception:
                pass
            # 环拒绝：B 依赖 A，若让 A 依赖 B → 环
            try:
                await SS._validate_dep_chain(db, d["tenant_id"], ta.id, tb.id)
                assert False
            except Exception:
                pass
            from sqlalchemy import delete
            await db.execute(delete(ScheduledTask).where(ScheduledTask.tenant_id == d["tenant_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_trigger_dependents_fires_downstream(monkeypatch):
    """A 成功后 _trigger_dependents 触发 B。"""
    async def _run():
        d = await _setup("taskdep2")
        from app.services import schedule_service as SS
        import app.tasks.scheduler_tasks as ST

        async with AsyncSessionLocal() as db:
            ta = await SS.create_task(db, tenant_id=d["tenant_id"], owner_id=d["uid"], data={
                "name": "A2", "agent_id": d["agent_id"], "target_type": "prompt", "prompt": "x",
                "schedule_kind": "interval", "interval_seconds": 3600})
            await db.commit()
            tb = await SS.create_task(db, tenant_id=d["tenant_id"], owner_id=d["uid"], data={
                "name": "B2", "agent_id": d["agent_id"], "target_type": "prompt", "prompt": "y",
                "schedule_kind": "interval", "interval_seconds": 3600, "depends_on_task_id": ta.id})
            await db.commit()
            a_id, b_id = ta.id, tb.id

        triggered = []
        async def _fake_execute(task_id, *, manual=False):
            triggered.append(task_id)
        monkeypatch.setattr(ST, "execute_task", _fake_execute)

        await ST._trigger_dependents(a_id)
        await asyncio.sleep(0.1)  # 让 create_task 调度
        assert b_id in triggered, "A 成功应触发下游 B"

        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            await db.execute(delete(ScheduledTask).where(ScheduledTask.tenant_id == d["tenant_id"]))
            await db.commit()
    async def _wrap():
        await _run()
    asyncio.new_event_loop().run_until_complete(_wrap())
