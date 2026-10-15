"""健壮性补强测试：LLM 重试、后台任务守护、HITL 恢复、产物 TTL。"""
from __future__ import annotations

import asyncio

import httpx
import pytest


# ---------- 1. 重试 ----------
def test_retry_mixin_classifies_retryable():
    from app.providers.drivers._retry import RetryMixin

    class D(RetryMixin):
        max_retries = 2

    req = httpx.Request("GET", "http://x")
    # 可重试：超时/网络/429/5xx
    assert D._is_retryable(httpx.TimeoutException("t"))
    assert D._is_retryable(httpx.ConnectError("c"))
    assert D._is_retryable(httpx.HTTPStatusError("429", request=req, response=httpx.Response(429)))
    assert D._is_retryable(httpx.HTTPStatusError("500", request=req, response=httpx.Response(500)))
    # 不可重试：400/401/404
    assert not D._is_retryable(httpx.HTTPStatusError("400", request=req, response=httpx.Response(400)))
    assert not D._is_retryable(httpx.HTTPStatusError("401", request=req, response=httpx.Response(401)))


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient(monkeypatch):
    """第一次 500、第二次 200 → 重试成功。"""
    from app.providers.drivers._retry import RetryMixin

    calls = {"n": 0}

    class FakeClient:
        async def request(self, method, url, **kw):
            calls["n"] += 1
            code = 500 if calls["n"] == 1 else 200
            return httpx.Response(code, request=httpx.Request(method, url))

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    class D(RetryMixin):
        max_retries = 2

    resp = await D()._request_with_retry(FakeClient(), "POST", "http://x")
    assert resp.status_code == 200 and calls["n"] == 2


@pytest.mark.asyncio
async def test_retry_gives_up_and_raises(monkeypatch):
    """持续 500 → 重试耗尽后抛出。"""
    from app.providers.drivers._retry import RetryMixin

    class FakeClient:
        async def request(self, method, url, **kw):
            return httpx.Response(500, request=httpx.Request(method, url))

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    class D(RetryMixin):
        max_retries = 1  # 1 次重试 = 共 2 次请求

    with pytest.raises(httpx.HTTPStatusError):
        await D()._request_with_retry(FakeClient(), "POST", "http://x")


# ---------- 2. 后台任务守护 ----------
def test_bg_spawn_tracks_and_reaps():
    from app.tasks import bg

    async def _run():
        async def ok():
            return 1

        await bg.shutdown(1)  # 清场
        t = bg.spawn("t_ok", ok())
        assert bg.pending_count() == 1
        await asyncio.sleep(0.05)
        assert t.done() and bg.pending_count() == 0

    asyncio.new_event_loop().run_until_complete(_run())


def test_bg_spawn_captures_exception():
    from app.tasks import bg

    async def _run():
        async def boom():
            raise RuntimeError("bg fail")

        await bg.shutdown(1)
        t = bg.spawn("t_boom", boom())
        await asyncio.sleep(0.05)
        assert t.done()
        # 异常被 done_callback 汇聚（不抛给事件循环），任务已从集合移除
        assert bg.pending_count() == 0

    asyncio.new_event_loop().run_until_complete(_run())


# ---------- 3. HITL 恢复 ----------
def test_hitl_recover_marks_stuck_approved():
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import AgentAction, Tenant
    from sqlalchemy import select

    async def _run():
        await init_models()
        from datetime import datetime, timedelta, timezone

        old = datetime.now(timezone.utc) - timedelta(hours=1)
        fresh = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "hitl"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="H", slug="hitl"); db.add(t); await db.flush()
            a = AgentAction(tenant_id=t.id, tool_name="x", tool_kind="write",
                            status="approved", created_at=old)   # 超宽限 → 应恢复
            b = AgentAction(tenant_id=t.id, tool_name="y", tool_kind="write",
                            status="approved", created_at=fresh)  # 宽限内 → 保留
            db.add(a); db.add(b); await db.commit()
            aid, bid = a.id, b.id

        from app.tasks.hitl_recover import recover_stuck_actions

        async with AsyncSessionLocal() as db:
            n = await recover_stuck_actions(db)
            assert n >= 1
            db.expire_all()
            assert (await db.get(AgentAction, aid)).status == "failed"
            assert (await db.get(AgentAction, bid)).status == "approved"  # 宽限期内保留
    asyncio.new_event_loop().run_until_complete(_run())


# ---------- 4. 产物 TTL ----------
def test_artifact_default_ttl_applied(monkeypatch):
    """生成的产物应带 expires_at（默认 TTL>0 时）。"""
    from app.agents.tools.base import ToolContext
    from app.agents.tools.file_tools import _save_artifact
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Artifact, Tenant, User
    from app.services.permission import PrincipalSet
    from sqlalchemy import select

    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "ttl"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="T", slug="ttl"); db.add(t); await db.flush()
            u = User(tenant_id=t.id, username="ttl_u", password_hash="x"); db.add(u); await db.flush()
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=u.id, tenant_id=t.id),
                              tenant_id=t.id, user_id=u.id)
            fk, art, _ = _save_artifact(ctx, "t.txt", b"hi", "text/plain")
            await db.flush()
            assert art.expires_at is not None, "应带默认 TTL"

    asyncio.new_event_loop().run_until_complete(_run())


def test_retrieval_miss_cleanup():
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import RetrievalMiss, Tenant
    from app.tasks.artifact_tasks import cleanup_retrieval_misses
    from sqlalchemy import select

    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "rm"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="R", slug="rm"); db.add(t); await db.flush()
            from datetime import datetime, timedelta, timezone

            old = datetime.now(timezone.utc) - timedelta(days=60)
            db.add(RetrievalMiss(tenant_id=t.id, query="old", created_at=old))  # 很久以前
            await db.commit()
        async with AsyncSessionLocal() as db:
            n = await cleanup_retrieval_misses(db, keep_days=30)
            assert n >= 1

    asyncio.new_event_loop().run_until_complete(_run())


# ---------- 5. 列表分页 ----------
def test_messages_cursor_pagination():
    """消息列表：limit 取最近 N 条；before_id 游标取更早；不传=全量（兼容）。"""
    from app.api.v1.chat import list_messages
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Conversation, Message, Tenant, User
    from sqlalchemy import select

    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "pg"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="P", slug="pg"); db.add(t); await db.flush()
            u = User(tenant_id=t.id, username="pg_u", password_hash="x"); db.add(u); await db.flush()
            conv = Conversation(tenant_id=t.id, user_id=u.id, title="分页")
            db.add(conv); await db.flush()
            for i in range(8):
                db.add(Message(tenant_id=t.id, conversation_id=conv.id, role="user", content=f"m{i}"))
            await db.commit()
            uid, cid = u.id, conv.id

        class U:
            id = uid
            tenant_id = t.id

        async with AsyncSessionLocal() as db:
            # 全量
            allm = await list_messages(cid, before_id=None, limit=None, user=U(), db=db)
            assert len(allm) == 8
            # 最近 3 条（应按 id 升序，内容是 m5,m6,m7）
            last3 = await list_messages(cid, before_id=None, limit=3, user=U(), db=db)
            assert [m.content for m in last3] == ["m5", "m6", "m7"]
            # 游标：取 m5 之前
            first_id = last3[0].id
            older = await list_messages(cid, before_id=first_id, limit=3, user=U(), db=db)
            assert [m.content for m in older] == ["m2", "m3", "m4"]

    asyncio.new_event_loop().run_until_complete(_run())


def test_conversations_cursor_pagination():
    from app.api.v1.chat import list_conversations
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Conversation, Tenant, User
    from sqlalchemy import select

    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "pgc"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="PC", slug="pgc"); db.add(t); await db.flush()
            u = User(tenant_id=t.id, username="pgc_u", password_hash="x"); db.add(u); await db.flush()
            for i in range(5):
                db.add(Conversation(tenant_id=t.id, user_id=u.id, title=f"c{i}"))
            await db.commit()
            uid = u.id

        class U:
            id = uid
            tenant_id = t.id

        async with AsyncSessionLocal() as db:
            first = await list_conversations(before_id=None, limit=2, user=U(), db=db)
            assert len(first) == 2
            # 倒序 → 最新两条
            older = await list_conversations(before_id=first[-1].id, limit=2, user=U(), db=db)
            assert len(older) == 2
            assert older[0].id < first[-1].id

    asyncio.new_event_loop().run_until_complete(_run())


def test_documents_optional_pagination():
    from app.api.v1.document import list_documents
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Document, KnowledgeBase, Tenant, User
    from sqlalchemy import select

    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "pgd"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="PD", slug="pgd"); db.add(t); await db.flush()
            u = User(tenant_id=t.id, username="pgd_u", password_hash="x", is_admin=True)
            db.add(u); await db.flush()
            kb = KnowledgeBase(tenant_id=t.id, name="kb", visibility="public")
            db.add(kb); await db.flush()
            for i in range(4):
                db.add(Document(tenant_id=t.id, kb_id=kb.id, title=f"d{i}", status="ready"))
            await db.commit()
            kb_id, uid = kb.id, u.id

        class U:
            id = uid
            tenant_id = t.id

        async with AsyncSessionLocal() as db:
            full = await list_documents(kb_id, before_id=None, limit=None, user=U(), db=db)
            assert len(full) == 4
            page = await list_documents(kb_id, before_id=None, limit=2, user=U(), db=db)
            assert len(page) == 2

    asyncio.new_event_loop().run_until_complete(_run())
