"""智能录单：JSON 容错解析、模板 CRUD、抽取落库、导出、AI 工具。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.ops_tools2 import ExtractRecordsTool
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import RecordEntry, RecordTemplate, Tenant, User
from app.services import record_extract_service as R
from app.services.permission import PrincipalSet


def test_extract_json_variants():
    assert R._extract_json('{"a":1}') == {"a": 1}
    assert R._extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert R._extract_json('前缀 [{"x":1},{"x":2}] 后缀') == [{"x": 1}, {"x": 2}]
    assert R._extract_json("完全不是 json") is None
    assert R._extract_json("") is None


def test_build_prompt_includes_fields():
    class T:
        fields = [{"name": "order_no", "label": "订单号", "type": "text", "required": True}]
        instructions = "电商订单"

    system, user = R.build_prompt(T(), "订单号 A123")
    assert "order_no" in system and "订单号" in system
    assert "电商订单" in system
    assert "A123" in user


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "rec"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="REC", slug="rec"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "rec_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="rec_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id}


def _ctx(db, d):
    return ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                       tenant_id=d["tenant_id"], user_id=d["user_id"])


def test_extract_records_with_fake_llm(monkeypatch):
    """mock LLM 返回 JSON → 抽取落库。"""
    async def _run():
        d = await _setup()

        class FakeRes:
            content = '[{"order_no": "A123", "customer": "张三", "amount": 199}, {"order_no": "A124", "customer": "李四", "amount": 88}]'

        class FakeLLM:
            async def chat(self, messages, **kw):
                return FakeRes()

        class RM:
            model_name = "fake"

        async def _fake_get_llm(db, *, tenant_id, config_id=None):
            return FakeLLM(), RM()

        monkeypatch.setattr("app.providers.registry.get_llm", _fake_get_llm)

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(
                tenant_id=d["tenant_id"], name="订单", fields=[
                    {"name": "order_no", "label": "订单号", "type": "text", "required": True},
                    {"name": "customer", "label": "客户", "type": "text"},
                    {"name": "amount", "label": "金额", "type": "number"},
                ],
            )
            db.add(t); await db.commit(); tid = t.id
        async with AsyncSessionLocal() as db:
            t = await db.get(RecordTemplate, tid)
            rows = await R.extract_records(db, tenant_id=d["tenant_id"], template=t, text="A123 张三 199; A124 李四 88")
            assert len(rows) == 2
            assert rows[0]["order_no"] == "A123" and rows[1]["customer"] == "李四"
            # 字段只保留模板定义的 key
            assert set(rows[0].keys()) == {"order_no", "customer", "amount"}
    asyncio.new_event_loop().run_until_complete(_run())


def test_tool_extract_and_list(monkeypatch):
    async def _run():
        d = await _setup()

        class FakeRes:
            content = '{"order_no": "B1", "customer": "王五"}'

        class FakeLLM:
            async def chat(self, messages, **kw):
                return FakeRes()

        class RM:
            model_name = "fake"

        async def _fake_get_llm(db, *, tenant_id, config_id=None):
            return FakeLLM(), RM()

        monkeypatch.setattr("app.providers.registry.get_llm", _fake_get_llm)

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="客户", fields=[
                {"name": "order_no", "label": "订单号"}, {"name": "customer", "label": "客户"}])
            db.add(t); await db.commit(); tid = t.id
        # list_templates
        async with AsyncSessionLocal() as db:
            r = await ExtractRecordsTool().run({"action": "list_templates"}, _ctx(db, d))
            assert "客户" in r.content and f"#{tid}" in r.content
        # extract（单对象 → 包成 1 条）
        async with AsyncSessionLocal() as db:
            r2 = await ExtractRecordsTool().run(
                {"action": "extract", "template_id": tid, "text": "B1 王五"}, _ctx(db, d))
            await db.commit()
            assert not r2.is_error and "1 条" in r2.content
        async with AsyncSessionLocal() as db:
            cnt = (await db.execute(select(RecordEntry).where(RecordEntry.template_id == tid))).scalars().all()
            assert len(cnt) == 1 and cnt[0].data["order_no"] == "B1"
    asyncio.new_event_loop().run_until_complete(_run())


def test_tool_bad_template():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await ExtractRecordsTool().run({"action": "extract", "template_id": 999999, "text": "x"}, _ctx(db, d))
            assert r.is_error and "不存在" in r.content
    asyncio.new_event_loop().run_until_complete(_run())


def test_endpoints_and_permissions():
    from app.api.v1.record_templates import router

    paths = {r.path for r in router.routes}
    assert "/record-templates" in paths
    assert any("extract" in p for p in paths)
    assert any("export" in p for p in paths)
    from app.services.permission_seed import PERMISSIONS
    codes = [p[0] for p in PERMISSIONS]
    assert "record:read" in codes and "record:manage" in codes


def test_tool_registered():
    from app.agents.tools.registry import registry

    t = registry.get_admin("extract_records")
    assert t is not None and t.required_permission == "record:manage"


def test_type_normalization():
    from app.services.record_extract_service import _normalize
    assert _normalize("number", "199元") == 199
    assert _normalize("number", "1,234.5") == 1234.5
    assert _normalize("number", 88) == 88
    assert _normalize("number", "abc") == "abc"  # 保留原值
    assert _normalize("date", "2026年1月5日") == "2026-01-05"
    assert _normalize("date", "2026/1/5") == "2026-01-05"
    assert _normalize("phone", "138-0000-0001") == "13800000001"
    assert _normalize("number", "") is None
    assert _normalize("text", None) is None


def test_extract_normalizes_types(monkeypatch):
    """抽取结果按字段类型归一化。"""
    async def _run():
        d = await _setup()

        class FakeRes:
            content = '[{"order_no": "A1", "amount": "199元", "date": "2026年1月5日"}]'

        class FakeLLM:
            async def chat(self, messages, **kw): return FakeRes()

        class RM: model_name = "fake"

        async def _fake(db, *, tenant_id, config_id=None): return FakeLLM(), RM()
        monkeypatch.setattr("app.providers.registry.get_llm", _fake)

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="归一化", fields=[
                {"name": "order_no", "label": "订单", "type": "text"},
                {"name": "amount", "label": "金额", "type": "number"},
                {"name": "date", "label": "日期", "type": "date"}])
            db.add(t); await db.commit(); tid = t.id
        async with AsyncSessionLocal() as db:
            t = await db.get(RecordTemplate, tid)
            rows = await R.extract_records(db, tenant_id=d["tenant_id"], template=t, text="A1 199元 2026年1月5日")
            assert rows[0]["amount"] == 199
            assert rows[0]["date"] == "2026-01-05"
    asyncio.new_event_loop().run_until_complete(_run())
