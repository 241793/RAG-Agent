"""问答页 HITL 续跑测试：确认写工具后，工具结果回灌 LLM 并落助手消息。

不依赖真实 LLM：mock get_llm 返回一个产出固定 delta 的假驱动。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import AgentAction, Conversation, Message, Tenant, User
from app.services.permission import PrincipalSet


class _FakeChunk:
    def __init__(self, delta="", reasoning=None, usage=None, finish=False):
        self.delta = delta
        self.reasoning = reasoning
        self.usage = usage
        self.finish = finish
        self.tool_calls = None


class _FakeLLM:
    """产出一段文本后结束（不调用工具）。"""

    async def chat(self, messages, *, model, stream=True, temperature=0.2, tools=None):
        async def _gen():
            yield _FakeChunk(delta="根据查询结果，")
            yield _FakeChunk(delta="北京 92# 汽油 8.61 元/升。")
            yield _FakeChunk(finish=True)
        return _gen()


class _FakeRM:
    model_name = "fake-model"
    config_id = 1


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "hitlresume"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="HITLR", slug="hitlresume"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "hitlresume_admin"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="hitlresume_admin", password_hash=hash_password("x"),
                     is_admin=True, display_name="管理员", user_type="internal")
            db.add(u); await db.flush()
        conv = Conversation(tenant_id=t.id, user_id=u.id, title="[hitl]续跑测试")
        db.add(conv); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id, "conv_id": conv.id}


def test_resume_answer_streams_and_persists(monkeypatch):
    async def _run():
        d = await _setup()
        import app.services.chat_service as cs

        async def _fake_llm(db, tenant_id, config_id=None):
            return _FakeLLM(), _FakeRM()

        monkeypatch.setattr(cs, "get_llm", _fake_llm)

        # 造一个已确认的 AgentAction（模拟 HITL 确认后）
        async with AsyncSessionLocal() as db:
            action = AgentAction(
                tenant_id=d["tenant_id"], conversation_id=d["conv_id"], user_id=d["uid"],
                tool_name="http_request", tool_kind="write",
                arguments={"url": "https://example.com", "method": "GET"},
                raw_tool_call={"id": "call_x", "name": "http_request", "arguments": "{}"},
                summary="请求 example.com", status="approved", expires_at=10**15,
            )
            db.add(action)
            await db.commit()
            aid = action.id

        from app.agents.tools.registry import registry

        tool = registry.get_builtin("http_request")

        async with AsyncSessionLocal() as db:
            action = await db.get(AgentAction, aid)
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tenant_id"], is_admin=True)
            events = []
            async for evt in cs.resume_answer(
                db, ps=ps, action=action, tool=tool,
                tool_result_text="HTTP 200 油价数据", allow_auto_write=True,
            ):
                events.append(evt)
        types = [e["type"] for e in events]
        assert "delta" in types, f"续跑应有 delta，实际 {types}"
        assert "done" in types, f"续跑应有 done，实际 {types}"
        text = "".join(e.get("text", "") for e in events if e["type"] == "delta")
        assert "8.61" in text

        # 落库了一条助手消息
        async with AsyncSessionLocal() as db:
            msgs = (await db.execute(
                select(Message).where(Message.conversation_id == d["conv_id"], Message.role == "assistant")
            )).scalars().all()
            assert msgs, "续跑后应落助手消息"
            assert any("8.61" in (m.content or "") for m in msgs)

    asyncio.new_event_loop().run_until_complete(_run())
