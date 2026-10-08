"""工具调用统计 + 工单批量/话术/转派 测试。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import AuditLog, ServiceTicket, ServiceTicketQuickReply, Tenant, User


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "batchsvc"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="BATCHSVC", slug="batchsvc"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "batch_admin"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="batch_admin", password_hash=hash_password("x"),
                     is_admin=True, display_name="管理员", user_type="internal")
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id}


# ---------------- 工具统计聚合 ----------------
def test_tool_stats_aggregation():
    async def _run():
        d = await _setup()
        tid = d["tenant_id"]
        async with AsyncSessionLocal() as db:
            now = int(time.time() * 1000)
            # 造审计：http_request 2 成功，find_skill 1 成功 1 失败
            for tool, result, lat in [
                ("http_request", "success", 120), ("http_request", "success", 80),
                ("find_skill", "success", 300), ("find_skill", "failure", None),
            ]:
                db.add(AuditLog(tenant_id=tid, action="chat.tool_call", resource_type="tool",
                                resource_id=tool, result=result, after={"latency_ms": lat},
                                created_at=now))
            await db.commit()

            from app.api.v1.usage import usage_tools
            fake_user = type("U", (), {"tenant_id": tid})()
            r = await usage_tools(days=1, user=fake_user, db=db)
            assert r["total"] == 4
            assert r["success"] == 3
            assert r["failure"] == 1
            by = {t["tool"]: t for t in r["by_tool"]}
            assert by["http_request"]["calls"] == 2 and by["http_request"]["success_rate"] == 1.0
            assert by["find_skill"]["failure"] == 1
            # 耗时均值
            assert by["http_request"]["avg_latency_ms"] == 100
            # 清理
            from sqlalchemy import delete
            await db.execute(delete(AuditLog).where(AuditLog.tenant_id == tid, AuditLog.action == "chat.tool_call"))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- 工单批量 ----------------
def test_ticket_bulk_and_resolve():
    async def _run():
        d = await _setup()
        tid, uid = d["tenant_id"], d["uid"]
        from app.services import service_ticket_service as S

        async with AsyncSessionLocal() as db:
            ids = []
            for i in range(3):
                t = ServiceTicket(tenant_id=tid, subject=f"工单{i}", status="open",
                                  priority="normal", source="manual", messages=[])
                db.add(t); await db.flush(); ids.append(t.id)
            await db.commit()

            # 批量改优先级
            r = await S.bulk_update(db, tenant_id=tid, ids=ids[:2], action="priority", value="urgent")
            await db.commit()
            assert r["updated"] == 2
            for i in ids[:2]:
                assert (await db.get(ServiceTicket, i)).priority == "urgent"
            # 批量解决
            r2 = await S.bulk_update(db, tenant_id=tid, ids=ids, action="resolve")
            await db.commit()
            assert r2["updated"] == 3
            for i in ids:
                assert (await db.get(ServiceTicket, i)).status == "resolved"
            # 非法动作
            try:
                await S.bulk_update(db, tenant_id=tid, ids=ids, action="nuke")
                assert False, "应拒绝非法动作"
            except ValueError:
                pass
            # 清理
            from sqlalchemy import delete
            await db.execute(delete(ServiceTicket).where(ServiceTicket.tenant_id == tid))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_ticket_list_filters():
    async def _run():
        d = await _setup()
        tid = d["tenant_id"]
        from app.services import service_ticket_service as S

        async with AsyncSessionLocal() as db:
            db.add(ServiceTicket(tenant_id=tid, subject="A", status="open", priority="urgent",
                                 source="channel", messages=[]))
            db.add(ServiceTicket(tenant_id=tid, subject="B", status="open", priority="low",
                                 source="manual", messages=[]))
            await db.commit()
            urgent = await S.list_tickets(db, tenant_id=tid, priority="urgent")
            assert len(urgent) == 1 and urgent[0].subject == "A"
            manual = await S.list_tickets(db, tenant_id=tid, source="manual")
            assert len(manual) == 1 and manual[0].subject == "B"
            from sqlalchemy import delete
            await db.execute(delete(ServiceTicket).where(ServiceTicket.tenant_id == tid))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- 话术库 ----------------
def test_quick_reply_crud():
    async def _run():
        d = await _setup()
        tid, uid = d["tenant_id"], d["uid"]
        async with AsyncSessionLocal() as db:
            qr = ServiceTicketQuickReply(tenant_id=tid, title="问候", content="您好，很高兴为您服务",
                                         scope="global", created_by=uid)
            db.add(qr); await db.flush()
            got = (await db.execute(select(ServiceTicketQuickReply).where(
                ServiceTicketQuickReply.tenant_id == tid))).scalars().first()
            assert got.title == "问候" and got.enabled is True
            from sqlalchemy import delete
            await db.execute(delete(ServiceTicketQuickReply).where(ServiceTicketQuickReply.tenant_id == tid))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- 快捷回复 / 批量 / 转派 端点已注册 ----------------
def test_service_endpoints_registered():
    import app.api.v1.service_tickets as st

    paths = {r.path for r in st.router.routes}
    assert "/service-tickets/bulk" in paths
    assert "/service-tickets/quick-replies" in paths
    assert "/service-tickets/{ticket_id}/assign" in paths
    assert "/service-tickets/{ticket_id}/resolve" in paths
