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


def test_build_prompt_puts_fields_in_user():
    """关键回归：字段定义与输出示例必须放进 **user** 消息。

    实测部分模型（deepseek 系）对 system 指令遵从度差：字段放 system 时会输出中文 key
    或 Markdown 列表，导致按英文字段名过滤后全为 null。故字段定义 + 示例须在 user。
    """
    class T:
        fields = [{"name": "order_no", "label": "订单号", "type": "text", "required": True},
                  {"name": "amount", "label": "金额", "type": "number"}]
        instructions = "电商订单"

    system, user = R.build_prompt(T(), "订单号 A123")
    # 字段定义、示例、原文都应在 user 里
    assert "order_no" in user and "订单号" in user
    assert "amount" in user and "电商订单" in user
    assert "A123" in user
    # 输出示例含英文字段名，引导模型对齐 key
    assert '"order_no"' in user
    # system 只作角色约束（不承载字段定义）
    assert "JSON" in system


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


def test_extract_records_needs_confirm_by_action():
    """HITL 按 action 判定：只读的 list_templates 免确认；extract+save 需确认。"""
    from app.agents.tools.ops_tools2 import ExtractRecordsTool

    t = ExtractRecordsTool()
    assert t.needs_confirm({"action": "list_templates"}) is False, "只读查询不应要确认"
    assert t.needs_confirm({"action": "extract", "save": False}) is False, "试抽不落库，免确认"
    assert t.needs_confirm({"action": "extract", "save": True}) is True, "落库抽取需确认"
    assert t.needs_confirm({"action": "extract"}) is True, "默认 save=True，需确认"


def test_tool_registered_as_resident_builtin():
    """extract_records 必须是**常驻内置**工具（不是仅 admin 池）。

    回归：曾只注册在 admin 池，模型看不到 → 用户给一条订单文本，AI 只能手工排版+反问。
    产出型工具（数据→结果）必须常驻，模型才调得到。
    """
    from app.agents.tools.registry import registry

    resident = {t.name for t in registry.all_builtin()}
    assert "extract_records" in resident, "extract_records 应常驻下发"
    t = registry.get_builtin("extract_records")
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


def test_normalize_keys_maps_label_and_case():
    """key 归一化：中文 label / 大小写 / 空格 → 英文字段名（修复"全 null"的另一半）。"""
    from app.services.record_extract_service import _normalize_records

    class T:
        fields = [{"name": "order_no", "label": "订单号", "type": "text"},
                  {"name": "customer", "label": "客户", "type": "text"},
                  {"name": "amount", "label": "金额", "type": "number"}]

    # 模型把 key 写成中文 label
    rows = _normalize_records([{"订单号": "A1", "客户": "张三", "金额": "199元"}], T())
    assert rows[0]["order_no"] == "A1" and rows[0]["customer"] == "张三" and rows[0]["amount"] == 199
    # 大小写/空格差异
    rows2 = _normalize_records([{"Order No": "A2", "CUSTOMER": "李四"}], T())
    assert rows2[0]["order_no"] == "A2" and rows2[0]["customer"] == "李四"
    # 完全对不上的 key 也不丢（追加保留）
    rows3 = _normalize_records([{"order_no": "A3", "备注": "加急"}], T())
    assert rows3[0]["order_no"] == "A3" and rows3[0].get("备注") == "加急"


def test_extract_retries_once_on_all_empty(monkeypatch):
    """首次返回全 null 时应自动重试一次（针对模型的"没抽到"回复）。"""
    async def _run():
        d = await _setup()
        calls = {"n": 0}

        class FakeLLM:
            async def chat(self, messages, **kw):
                calls["n"] += 1
                # 第一次返回全 null，第二次才给正确结果
                content = ('{"order_no": null, "customer": null}' if calls["n"] == 1
                           else '{"order_no": "A9", "customer": "王五"}')

                class R:
                    pass

                R.content = content
                return R()

        class RM:
            model_name = "fake"

        async def _fake(db, *, tenant_id, config_id=None):
            return FakeLLM(), RM()

        monkeypatch.setattr("app.providers.registry.get_llm", _fake)
        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="重试", fields=[
                {"name": "order_no", "label": "订单号"}, {"name": "customer", "label": "客户"}])
            db.add(t); await db.commit(); tid = t.id
        async with AsyncSessionLocal() as db:
            t = await db.get(RecordTemplate, tid)
            rows = await R.extract_records(db, tenant_id=d["tenant_id"], template=t, text="A9 王五")
            assert calls["n"] == 2, "应重试一次"
            assert rows[0]["order_no"] == "A9" and rows[0]["customer"] == "王五"
    asyncio.new_event_loop().run_until_complete(_run())


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


def test_batch_entries_delete_and_confirm():
    """批量端点：delete 删除、confirm/unconfirm 改状态；越权/跨租户不误伤。"""
    async def _run():
        from app.api.v1.record_templates import batch_entries
        from app.schemas.record_template import EntryBatchIn

        d = await _setup()

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="批量",
                               fields=[{"name": "a", "label": "A"}])
            db.add(t); await db.flush(); tid = t.id
            ids = []
            for i in range(3):
                e = RecordEntry(tenant_id=d["tenant_id"], template_id=tid,
                                data={"a": f"v{i}"}, status="draft")
                db.add(e); await db.flush(); ids.append(e.id)
            await db.commit()

        # 批量确认 2 条
        async with AsyncSessionLocal() as db:
            r = await batch_entries(EntryBatchIn(action="confirm", ids=ids[:2]), user=U(), db=db)
            await db.commit()
            assert r["affected"] == 2
        async with AsyncSessionLocal() as db:
            got = {e.id: e.status for e in (await db.execute(
                select(RecordEntry).where(RecordEntry.id.in_(ids)))).scalars().all()}
            assert got[ids[0]] == "confirmed" and got[ids[2]] == "draft"

        # 批量退回草稿
        async with AsyncSessionLocal() as db:
            await batch_entries(EntryBatchIn(action="unconfirm", ids=ids[:2]), user=U(), db=db)
            await db.commit()
            got = {e.id: e.status for e in (await db.execute(
                select(RecordEntry).where(RecordEntry.id.in_(ids)))).scalars().all()}
            assert got[ids[0]] == "draft"

        # 批量删除全部 3 条
        async with AsyncSessionLocal() as db:
            r = await batch_entries(EntryBatchIn(action="delete", ids=ids), user=U(), db=db)
            await db.commit()
            assert r["affected"] == 3
            left = (await db.execute(select(RecordEntry).where(RecordEntry.id.in_(ids)))).scalars().all()
            assert not left
    asyncio.new_event_loop().run_until_complete(_run())


def test_batch_entries_rejects_bad_action_and_empty():
    async def _run():
        from app.api.v1.record_templates import batch_entries
        from app.core.errors import ValidationError
        from app.schemas.record_template import EntryBatchIn

        d = await _setup()

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            try:
                await batch_entries(EntryBatchIn(action="explode", ids=[1]), user=U(), db=db)
                raise AssertionError("应拒绝非法 action")
            except ValidationError:
                pass
            try:
                await batch_entries(EntryBatchIn(action="delete", ids=[]), user=U(), db=db)
                raise AssertionError("应拒绝空 ids")
            except ValidationError:
                pass
    asyncio.new_event_loop().run_until_complete(_run())


def test_list_entries_keyword_and_status_filter():
    """记录列表：keyword 跨字段模糊匹配 + status 过滤。"""
    async def _run():
        from app.api.v1.record_templates import list_entries

        d = await _setup()

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="搜索",
                               fields=[{"name": "customer", "label": "客户"},
                                       {"name": "amount", "label": "金额"}])
            db.add(t); await db.flush(); tid = t.id
            db.add(RecordEntry(tenant_id=d["tenant_id"], template_id=tid,
                               data={"customer": "张三", "amount": 199}, status="confirmed"))
            db.add(RecordEntry(tenant_id=d["tenant_id"], template_id=tid,
                               data={"customer": "李四", "amount": 88}, status="draft"))
            await db.commit()

        async with AsyncSessionLocal() as db:
            allr = await list_entries(tid, user=U(), db=db)
            assert len(allr) == 2
            # 按客户名搜
            hit = await list_entries(tid, keyword="张三", user=U(), db=db)
            assert len(hit) == 1 and hit[0]["data"]["customer"] == "张三"
            # 按金额搜（跨字段：值是数字也能匹配）
            hit2 = await list_entries(tid, keyword="88", user=U(), db=db)
            assert len(hit2) == 1 and hit2[0]["data"]["customer"] == "李四"
            # 状态过滤
            conf = await list_entries(tid, status="confirmed", user=U(), db=db)
            assert len(conf) == 1 and conf[0]["status"] == "confirmed"
            # 中文状态名也能搜
            drafts = await list_entries(tid, keyword="草稿", user=U(), db=db)
            assert len(drafts) == 1 and drafts[0]["status"] == "draft"
    asyncio.new_event_loop().run_until_complete(_run())


def test_extract_from_document_source(monkeypatch):
    """从知识库文档录单：给 doc_id 时取文档正文，source_type=document、source_ref=doc_id。"""
    async def _run():
        from app.api.v1.record_templates import extract
        from app.schemas.record_template import ExtractIn
        from app.models import Document, KnowledgeBase

        d = await _setup()

        class FakeRes:
            content = '{"customer": "张三", "amount": 199}'

        class FakeLLM:
            async def chat(self, messages, **kw): return FakeRes()

        class RM: model_name = "fake"

        async def _fake(db, *, tenant_id, config_id=None): return FakeLLM(), RM()
        monkeypatch.setattr("app.providers.registry.get_llm", _fake)

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            kb = KnowledgeBase(tenant_id=d["tenant_id"], name="KB", visibility="private")
            db.add(kb); await db.flush()
            doc = Document(tenant_id=d["tenant_id"], kb_id=kb.id, title="订单邮件",
                           status="ready", content="客户张三，金额199元")
            db.add(doc); await db.flush()
            t = RecordTemplate(tenant_id=d["tenant_id"], name="文档录单", fields=[
                {"name": "customer", "label": "客户"}, {"name": "amount", "label": "金额", "type": "number"}])
            db.add(t); await db.flush()
            doc_id, tid = doc.id, t.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            r = await extract(ExtractIn(template_id=tid, doc_id=doc_id, save=True), user=U(), db=db)
            await db.commit()
            assert r["count"] == 1 and r["source_type"] == "document"
        async with AsyncSessionLocal() as db:
            e = (await db.execute(select(RecordEntry).where(RecordEntry.template_id == tid))).scalars().first()
            assert e.source_type == "document" and e.source_ref == str(doc_id)
            assert e.data["customer"] == "张三"
    asyncio.new_event_loop().run_until_complete(_run())


def test_list_entries_returns_source_fields():
    """记录列表返回 source_ref/raw_text 等来源字段（供前端追溯）。"""
    async def _run():
        from app.api.v1.record_templates import list_entries

        d = await _setup()

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="来源", fields=[{"name": "a", "label": "A"}])
            db.add(t); await db.flush(); tid = t.id
            db.add(RecordEntry(tenant_id=d["tenant_id"], template_id=tid, data={"a": "x"},
                               source_type="channel", source_ref="u123", raw_text="原始消息内容"))
            await db.commit()

        async with AsyncSessionLocal() as db:
            items = await list_entries(tid, user=U(), db=db)
            assert len(items) == 1
            it = items[0]
            assert it["source_type"] == "channel" and it["source_ref"] == "u123"
            assert it["raw_text"] == "原始消息内容"
    asyncio.new_event_loop().run_until_complete(_run())


def test_export_status_filter():
    """导出支持按状态过滤（只导已确认）。"""
    async def _run():
        from app.api.v1.record_templates import export_entries

        d = await _setup()

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="导出", fields=[{"name": "c", "label": "客户"}])
            db.add(t); await db.flush(); tid = t.id
            db.add(RecordEntry(tenant_id=d["tenant_id"], template_id=tid, data={"c": "已确认客户"}, status="confirmed"))
            db.add(RecordEntry(tenant_id=d["tenant_id"], template_id=tid, data={"c": "草稿客户"}, status="draft"))
            await db.commit()

        async with AsyncSessionLocal() as db:
            resp = await export_entries(tid, fmt="csv", status="confirmed", user=U(), db=db)
            body = b"".join([c async for c in resp.body_iterator]).decode("utf-8-sig")
            assert "已确认客户" in body and "草稿客户" not in body
    asyncio.new_event_loop().run_until_complete(_run())


def test_search_docs_endpoint():
    """文档搜索端点：仅返回已解析且有正文的文档。"""
    async def _run():
        from app.api.v1.record_templates import search_docs
        from app.models import Document, KnowledgeBase

        d = await _setup()

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            kb = KnowledgeBase(tenant_id=d["tenant_id"], name="KB2", visibility="private")
            db.add(kb); await db.flush()
            db.add(Document(tenant_id=d["tenant_id"], kb_id=kb.id, title="客户订单汇总",
                            status="ready", content="有正文"))
            db.add(Document(tenant_id=d["tenant_id"], kb_id=kb.id, title="空文档",
                            status="ready", content=""))
            await db.commit()

        async with AsyncSessionLocal() as db:
            rows = await search_docs(keyword=None, user=U(), db=db)
            titles = [r["title"] for r in rows]
            assert "客户订单汇总" in titles and "空文档" not in titles
    asyncio.new_event_loop().run_until_complete(_run())


def test_extract_auto_confirm_lands_confirmed(monkeypatch):
    """免确认模式（auto_confirm=True）：抽取直接落 confirmed，跳过人工核对。"""
    async def _run():
        from app.api.v1.record_templates import extract
        from app.schemas.record_template import ExtractIn

        d = await _setup()

        class FakeRes:
            content = '{"customer": "张三", "amount": 199}'

        class FakeLLM:
            async def chat(self, messages, **kw): return FakeRes()

        class RM: model_name = "fake"

        async def _fake(db, *, tenant_id, config_id=None): return FakeLLM(), RM()
        monkeypatch.setattr("app.providers.registry.get_llm", _fake)

        class U:
            tenant_id = d["tenant_id"]
            id = d["user_id"]

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="自动确认", fields=[
                {"name": "customer", "label": "客户"}, {"name": "amount", "label": "金额", "type": "number"}])
            db.add(t); await db.flush(); tid = t.id
            await db.commit()

        # 免确认 → confirmed
        async with AsyncSessionLocal() as db:
            r = await extract(ExtractIn(template_id=tid, text="张三 199", auto_confirm=True), user=U(), db=db)
            await db.commit()
            assert r["status"] == "confirmed"
        async with AsyncSessionLocal() as db:
            e = (await db.execute(select(RecordEntry).where(RecordEntry.template_id == tid))).scalars().first()
            assert e.status == "confirmed"

        # 默认（确认开启）→ draft
        async with AsyncSessionLocal() as db:
            r2 = await extract(ExtractIn(template_id=tid, text="张三 199"), user=U(), db=db)
            await db.commit()
            assert r2["status"] == "draft"
    asyncio.new_event_loop().run_until_complete(_run())


def test_extract_tool_respects_auto_write(monkeypatch):
    """AI 工具路径：ctx.auto_write=True（免确认执行）时抽取落 confirmed。"""
    async def _run():
        from app.agents.tools.ops_tools2 import ExtractRecordsTool

        d = await _setup()

        class FakeRes:
            content = '{"order_no": "B9", "customer": "王五"}'

        class FakeLLM:
            async def chat(self, messages, **kw): return FakeRes()

        class RM: model_name = "fake"

        async def _fake(db, *, tenant_id, config_id=None): return FakeLLM(), RM()
        monkeypatch.setattr("app.providers.registry.get_llm", _fake)

        async with AsyncSessionLocal() as db:
            t = RecordTemplate(tenant_id=d["tenant_id"], name="工具自动", fields=[
                {"name": "order_no", "label": "订单号"}, {"name": "customer", "label": "客户"}])
            db.add(t); await db.commit(); tid = t.id

        # auto_write=True
        async with AsyncSessionLocal() as db:
            ctx = _ctx(db, d); ctx.auto_write = True
            r = await ExtractRecordsTool().run(
                {"action": "extract", "template_id": tid, "text": "B9 王五"}, ctx)
            await db.commit()
            assert not r.is_error and r.data["status"] == "confirmed"
        async with AsyncSessionLocal() as db:
            e = (await db.execute(select(RecordEntry).where(RecordEntry.template_id == tid))).scalars().first()
            assert e.status == "confirmed"

        # auto_write=False（默认）→ draft
        async with AsyncSessionLocal() as db:
            ctx2 = _ctx(db, d)  # 默认 auto_write=False
            r2 = await ExtractRecordsTool().run(
                {"action": "extract", "template_id": tid, "text": "B9 王五"}, ctx2)
            await db.commit()
            assert r2.data["status"] == "draft"
    asyncio.new_event_loop().run_until_complete(_run())


def test_channel_record_bound_vs_unbound_status(monkeypatch):
    """渠道 /录单：已绑定内部账号 → confirmed；未绑定外部客户 → draft。"""
    async def _run():
        from app.channels.commands import CommandContext, cmd_record
        from app.models import Channel, ChannelUser

        d = await _setup()

        class FakeRes:
            content = '{"customer": "张三", "amount": 199}'

        class FakeLLM:
            async def chat(self, messages, **kw): return FakeRes()

        class RM: model_name = "fake"

        async def _fake(db, *, tenant_id, config_id=None): return FakeLLM(), RM()
        monkeypatch.setattr("app.providers.registry.get_llm", _fake)

        async with AsyncSessionLocal() as db:
            ch = Channel(tenant_id=d["tenant_id"], kind="wework", name="录单渠道", enabled=True)
            db.add(ch); await db.flush()
            t = RecordTemplate(tenant_id=d["tenant_id"], name="渠道录单", fields=[
                {"name": "customer", "label": "客户"}, {"name": "amount", "label": "金额", "type": "number"}])
            db.add(t); await db.flush()
            u = await db.get(User, d["user_id"])
            # 已绑定
            cu_bind = ChannelUser(tenant_id=d["tenant_id"], channel="wework", external_id="e_bind",
                                  user_id=u.id, bound_user_id=u.id)
            # 未绑定
            cu_free = ChannelUser(tenant_id=d["tenant_id"], channel="wework", external_id="e_free",
                                  user_id=u.id, bound_user_id=None)
            db.add(cu_bind); db.add(cu_free); await db.commit()
            tid = t.id

        # 已绑定 → confirmed
        async with AsyncSessionLocal() as db:
            cu = (await db.execute(select(ChannelUser).where(ChannelUser.external_id == "e_bind"))).scalars().first()
            ch2 = (await db.execute(select(Channel).where(Channel.name == "录单渠道"))).scalars().first()
            u = await db.get(User, d["user_id"])
            ctx = CommandContext(db=db, channel=ch2, channel_user=cu, user=u, ps=None)
            r = await cmd_record(ctx, [str(tid), "张三 199"])
            await db.commit()
            assert "已自动确认" in r, r
        async with AsyncSessionLocal() as db:
            e = (await db.execute(select(RecordEntry).where(RecordEntry.source_ref.is_(None),
                 RecordEntry.source_type == "channel"))).scalars().all()
            assert e and e[0].status == "confirmed"

        # 未绑定 → draft
        async with AsyncSessionLocal() as db:
            cu = (await db.execute(select(ChannelUser).where(ChannelUser.external_id == "e_free"))).scalars().first()
            ch2 = (await db.execute(select(Channel).where(Channel.name == "录单渠道"))).scalars().first()
            u = await db.get(User, d["user_id"])
            ctx = CommandContext(db=db, channel=ch2, channel_user=cu, user=u, ps=None)
            r = await cmd_record(ctx, [str(tid), "李四 88"])
            await db.commit()
            assert "已自动确认" not in r, r
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(RecordEntry).where(RecordEntry.source_type == "channel"))).scalars().all()
            statuses = sorted(e.status for e in rows)
            assert "draft" in statuses and "confirmed" in statuses
    asyncio.new_event_loop().run_until_complete(_run())
