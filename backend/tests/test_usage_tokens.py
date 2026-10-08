"""Token 用量归一化与聚合测试。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.models import ModelProvider, ModelConfig, Tenant, UsageLog, User
from app.services.usage_service import normalize_usage


def test_normalize_openai_shape():
    u = normalize_usage({"prompt_tokens": 100, "completion_tokens": 20,
                         "prompt_tokens_details": {"cached_tokens": 30}})
    assert u == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cached_tokens": 30}


def test_normalize_anthropi_shape():
    u = normalize_usage({"input_tokens": 7, "output_tokens": 3})
    assert u["prompt_tokens"] == 7 and u["completion_tokens"] == 3 and u["total_tokens"] == 10
    assert u["cached_tokens"] == 0


def test_normalize_empty():
    assert normalize_usage(None) == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    assert normalize_usage({"total_tokens": 42})["total_tokens"] == 42


async def _run_agg():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "ut"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="UT", slug="ut"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "ut_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="ut_u", password_hash="x"); db.add(u); await db.flush()
        await db.commit()
        tid, uid = t.id, u.id
    # 写两条 usage
    now = int(time.time() * 1000)
    async with AsyncSessionLocal() as db:
        db.add_all([
            UsageLog(tenant_id=tid, user_id=uid, conversation_id=999, purpose="chat",
                     prompt_tokens=100, completion_tokens=20, total_tokens=120, cached_tokens=30, created_at=now),
            UsageLog(tenant_id=tid, user_id=uid, conversation_id=999, purpose="chat",
                     prompt_tokens=50, completion_tokens=10, total_tokens=60, cached_tokens=0, created_at=now),
        ])
        await db.commit()
    # 聚合断言（等价接口 SQL）
    from sqlalchemy import func

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(func.count(), func.coalesce(func.sum(UsageLog.total_tokens), 0),
                   func.coalesce(func.sum(UsageLog.cached_tokens), 0))
            .where(UsageLog.conversation_id == 999, UsageLog.tenant_id == tid)
        )).one()
    assert row[0] == 2, row
    assert row[1] == 180, row
    assert row[2] == 30, row
    print("OK usage_tokens")


def test_usage_aggregate():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_agg())
    finally:
        loop.close()
        asyncio.set_event_loop(None)
