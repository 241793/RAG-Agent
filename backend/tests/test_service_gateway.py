"""客服对外网关 + SLA + 事件 + 满意度 + 内部备注。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import ServiceTicket, Tenant, User
from app.services import service_ticket_service as S


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "gw"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="GW", slug="gw"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "gw_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="gw_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id}


def test_sla_due_computed_by_priority():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="紧急", content="x",
                                      priority="urgent", notify=False)
            await db.commit()
            import time as _t
            assert t.sla_due_at is not None
            # urgent ≈ 建单时间 + 1h（sla_due_at 是 ms 时间戳）
            assert abs(t.sla_due_at - (int(_t.time() * 1000) + 3600 * 1000)) < 10000
    asyncio.new_event_loop().run_until_complete(_run())


def test_events_published(monkeypatch):
    async def _run():
        d = await _setup()
        events = []

        async def _fake_publish(name, *, tenant_id, payload=None):
            events.append(name); return 1

        monkeypatch.setattr("app.tasks.event_bus.publish", _fake_publish)
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="e", content="x", notify=False)
            await db.commit()
            await S.add_agent_reply(db, t, "回复", agent_id=d["user_id"])
            await db.commit()
            await S.close_ticket(db, t)
            await db.commit()
        assert "ticket.created" in events
        assert "ticket.replied" in events
        assert "ticket.closed" in events
    asyncio.new_event_loop().run_until_complete(_run())


def test_first_response_and_notes_and_rating():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="s", content="x", notify=False)
            await db.commit()
            assert t.first_response_at is None
            await S.add_agent_reply(db, t, "首次回复", agent_id=d["user_id"])
            await db.commit()
            assert t.first_response_at is not None
            await S.add_note(db, t, "内部备注：需退款", agent_id=d["user_id"])
            await db.commit()
            assert t.internal_notes[0]["content"].startswith("内部备注")
            await S.rate_ticket(db, t, 5, "很满意")
            await db.commit()
            assert t.satisfaction == 5 and t.satisfaction_comment == "很满意"
    asyncio.new_event_loop().run_until_complete(_run())


def test_sla_breach_scan():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="超时", content="x", notify=False)
            import time as _t
            t.sla_due_at = int(_t.time() * 1000) - 1000  # 已过期
            await db.commit(); tid = t.id
        async with AsyncSessionLocal() as db:
            n = await S.scan_sla_breaches(db, tenant_id=d["tenant_id"])
            assert n >= 1
        async with AsyncSessionLocal() as db:
            assert (await db.get(ServiceTicket, tid)).sla_breached is True
    asyncio.new_event_loop().run_until_complete(_run())


def test_gateway_endpoints_registered():
    from app.api.v1.service_api import router

    paths = {r.path for r in router.routes}
    assert "/service-gateway/tickets" in paths
    assert any("messages" in p for p in paths)
    assert any("rate" in p for p in paths)


def test_service_submit_permission_seeded():
    from app.services.permission_seed import PERMISSIONS, ROLES

    assert "service:submit" in [p[0] for p in PERMISSIONS]
    assert any(r[0] == "service_agent" for r in ROLES)


def test_ticket_source_field():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="api", content="x",
                                      source="api", notify=False)
            await db.commit()
            assert t.source == "api"
    asyncio.new_event_loop().run_until_complete(_run())
