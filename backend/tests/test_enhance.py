"""增强功能测试：RRF 权重、MMR 去冗余、查询改写、内容巡检、未命中日志、提醒扫描、图表导出。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Document, KnowledgeBase, Reminder, RetrievalMiss, Tenant, User
from app.retrieval.vector_store.store import VectorHit
from app.services import kb_audit_service as KA
from app.services import reminder_service as RS


async def _setup(slug="enh"):
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
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == t.id))).scalars().first()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name=f"{slug}-kb", owner_id=u.id)
            db.add(kb); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id, "kb_id": kb.id}


# ==================== RRF 权重 ====================
def test_rrf_weights_shift_ranking():
    from app.retrieval.fusion import rrf_fuse

    def h(cid):
        return VectorHit(chunk_id=cid, doc_id=cid, kb_id=1, content=f"c{cid}", score=0.0)

    # 两路：向量路 c1 第一；BM25 路 c2 第一。默认等权 → c1 与 c2 同分，c1 先（稳定）
    vec = [h(1), h(2)]
    bm = [h(2), h(1)]
    fused = rrf_fuse([vec, bm], top_n=2)
    assert abs(fused[0].score - fused[1].score) < 1e-12
    # 给 BM25 路更高权重 → c2 反超
    fused_w = rrf_fuse([vec, bm], top_n=2, weights=[0.5, 3.0])
    assert fused_w[0].chunk_id == 2
    assert fused_w[0].score > fused_w[1].score


def test_rrf_weights_length_mismatch_safe():
    from app.retrieval.fusion import rrf_fuse

    def h(cid):
        return VectorHit(chunk_id=cid, doc_id=cid, kb_id=1, content=f"c{cid}", score=0.0)

    # weights 少于路数 → 缺失路按 1.0，不报错
    fused = rrf_fuse([[h(1)], [h(2)]], top_n=2, weights=[2.0])
    assert len(fused) == 2


# ==================== MMR ====================
def test_mmr_drops_near_duplicates():
    async def _run():
        d = await _setup("mmr")
        from app.models import Chunk

        async with AsyncSessionLocal() as db:
            # 三个分块：1/2 向量几乎相同（近似重复），3 与它们正交
            db.add_all([
                Chunk(id=91001, tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=1, ordinal=0,
                      content="重复A", embedding=[1.0, 0.0, 0.0, 0.0]),
                Chunk(id=91002, tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=1, ordinal=1,
                      content="重复B", embedding=[0.99, 0.01, 0.0, 0.0]),
                Chunk(id=91003, tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=1, ordinal=2,
                      content="不同", embedding=[0.0, 0.0, 0.0, 1.0]),
            ])
            await db.commit()

            from app.retrieval.mmr import mmr_select
            hits = [
                VectorHit(chunk_id=91001, doc_id=1, kb_id=d["kb_id"], content="重复A", score=1.0),
                VectorHit(chunk_id=91002, doc_id=1, kb_id=d["kb_id"], content="重复B", score=0.95),
                VectorHit(chunk_id=91003, doc_id=1, kb_id=d["kb_id"], content="不同", score=0.5),
            ]
            out = await mmr_select(db, hits, top_k=2, lambda_=0.5)
            ids = {h.chunk_id for h in out}
            assert 91001 in ids, "最高相关应入选"
            assert 91003 in ids, "MMR 应选多样项而非近似重复"
            assert 91002 not in ids

            from sqlalchemy import delete
            await db.execute(delete(Chunk).where(Chunk.id.in_([91001, 91002, 91003])))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_mmr_noop_when_fewer_than_topk():
    async def _run():
        from app.retrieval.mmr import mmr_select
        hits = [VectorHit(chunk_id=1, doc_id=1, kb_id=1, content="x", score=1.0)]
        out = await mmr_select(None, hits, top_k=5)
        assert out is hits
    asyncio.new_event_loop().run_until_complete(_run())


# ==================== 查询改写 ====================
def test_needs_condense_detects_reference_words():
    from app.services.retrieval_service import _needs_condense

    assert _needs_condense("它的价格是多少") is True
    assert _needs_condense("那这个怎么用") is True
    assert _needs_condense("还有别的吗") is True
    # 短句（≤12 字）一律视为依赖上下文
    assert _needs_condense("报销流程") is True
    # 长句且无指代词 → 独立完整，无需改写
    assert _needs_condense("我们公司今年的差旅费报销标准和审批流程是什么") is False
    assert _needs_condense("") is False


def test_condense_query_falls_back_without_history():
    async def _run():
        from app.services.retrieval_service import condense_query

        # 无历史 → 原样返回，不调用 LLM
        out = await condense_query(None, tenant_id=1, query="它的价格", history=[])
        assert out == "它的价格"
    asyncio.new_event_loop().run_until_complete(_run())


# ==================== 内容巡检 ====================
def test_audit_kb_flags_problem_docs():
    async def _run():
        d = await _setup("audit")
        async with AsyncSessionLocal() as db:
            db.add_all([
                Document(tenant_id=d["tenant_id"], kb_id=d["kb_id"], title="空文档", kind="file",
                         status="ready", char_count=0, chunk_count=0),
                Document(tenant_id=d["tenant_id"], kb_id=d["kb_id"], title="失败文档", kind="file",
                         status="failed", char_count=0, chunk_count=0, error_msg="解析失败"),
                Document(tenant_id=d["tenant_id"], kb_id=d["kb_id"], title="好文档", kind="file",
                         status="ready", char_count=100, chunk_count=3, tags=["制度"]),
            ])
            await db.commit()

            audit = await KA.audit_kb(db, kb_id=d["kb_id"], tenant_id=d["tenant_id"])
            c = audit["counts"]
            assert c["failed"] >= 1 and c["empty"] >= 1
            titles = {r["title"] for r in audit["failed"]}
            assert "失败文档" in titles

            from sqlalchemy import delete
            await db.execute(delete(Document).where(Document.kb_id == d["kb_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_top_missed_queries_aggregates():
    async def _run():
        d = await _setup("miss")
        async with AsyncSessionLocal() as db:
            for _ in range(3):
                db.add(RetrievalMiss(tenant_id=d["tenant_id"], query="不存在的词", kb_ids=str(d["kb_id"])))
            db.add(RetrievalMiss(tenant_id=d["tenant_id"], query="偶尔的词", kb_ids=str(d["kb_id"])))
            await db.commit()

            tops = await KA.top_missed_queries(db, tenant_id=d["tenant_id"], days=30)
            assert tops and tops[0]["query"] == "不存在的词" and tops[0]["count"] >= 3

            from sqlalchemy import delete
            await db.execute(delete(RetrievalMiss).where(RetrievalMiss.tenant_id == d["tenant_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


# ==================== 提醒 ====================
def test_reminder_crud_and_done():
    async def _run():
        d = await _setup("rem")
        async with AsyncSessionLocal() as db:
            r = await RS.create_reminder(db, tenant_id=d["tenant_id"], creator_id=d["uid"],
                                         data={"title": "写周报", "due_at": int(time.time() * 1000) + 3600_000})
            await db.commit()
            rid = r.id
            assert r.status == "pending" and r.assignee_id == d["uid"]

            rows = await RS.list_reminders(db, tenant_id=d["tenant_id"])
            assert any(x.id == rid for x in rows)

            await RS.update_reminder(db, r, {"title": "写月报"})
            await db.commit()
            assert r.title == "写月报"

            await RS.mark_done(db, r)
            await db.commit()
            assert r.status == "done" and r.done_at

            from sqlalchemy import delete
            await db.execute(delete(Reminder).where(Reminder.tenant_id == d["tenant_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_scan_due_reminders_fires_and_reschedules(monkeypatch):
    async def _run():
        d = await _setup("rem2")
        now = int(time.time() * 1000)
        async with AsyncSessionLocal() as db:
            # 已到期 + 每小时重复
            r = Reminder(tenant_id=d["tenant_id"], title="巡检", status="pending",
                         due_at=now - 1000, notify_on_due=True, repeat_cron="0 * * * *",
                         assignee_id=d["uid"], creator_id=d["uid"])
            # 未到期
            r2 = Reminder(tenant_id=d["tenant_id"], title="未来", status="pending",
                          due_at=now + 3600_000, notify_on_due=True,
                          assignee_id=d["uid"], creator_id=d["uid"])
            db.add_all([r, r2])
            await db.commit()
            r_id, r2_id = r.id, r2.id

        dispatched = []

        async def _fake_dispatch(db, *, tenant_id, msg, user_id):
            dispatched.append(msg.title)
        import app.notifiers.registry as reg
        monkeypatch.setattr(reg, "dispatch", _fake_dispatch)

        async with AsyncSessionLocal() as db:
            n = await RS.scan_due_reminders(db, now_ms=now)
            assert n == 1, "只应触发已到期那条"
            assert any("巡检" in t for t in dispatched)
            # 重复日程重算下次 due 且清空 notified_at
            r = await db.get(Reminder, r_id)
            assert r.due_at > now and r.notified_at is None
            r2 = await db.get(Reminder, r2_id)
            assert r2.notified_at is None

            from sqlalchemy import delete
            await db.execute(delete(Reminder).where(Reminder.tenant_id == d["tenant_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_scan_due_reminders_not_duplicated():
    async def _run():
        d = await _setup("rem3")
        now = int(time.time() * 1000)
        async with AsyncSessionLocal() as db:
            r = Reminder(tenant_id=d["tenant_id"], title="不重复", status="pending",
                         due_at=now - 1000, notify_on_due=True,
                         assignee_id=d["uid"], creator_id=d["uid"])
            db.add(r); await db.commit()
            r_id = r.id
        async with AsyncSessionLocal() as db:
            n1 = await RS.scan_due_reminders(db, now_ms=now)
            n2 = await RS.scan_due_reminders(db, now_ms=now + 1000)
            assert n1 == 1 and n2 == 0, "无重复日程不应重复提醒"
            from sqlalchemy import delete
            await db.execute(delete(Reminder).where(Reminder.tenant_id == d["tenant_id"]))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


# ==================== 图表导出 ====================
def test_render_xlsx_with_charts():
    from app.agents.tools.file_tools import _render_xlsx

    data = _render_xlsx(
        "季度销售\nQ1,100\nQ2,150",
        rows=[["季度", "销售额"], ["Q1", 100], ["Q2", 150]],
        charts=[{"type": "bar", "title": "销售额", "categories": ["Q1", "Q2"], "values": [100, 150]}],
        sheet_name="销售",
    )
    assert isinstance(data, bytes) and len(data) > 0
    assert data[:2] == b"PK", "xlsx 应为 zip 容器"


def test_render_xlsx_pie_and_line():
    from app.agents.tools.file_tools import _render_xlsx

    for ctype in ("pie", "line"):
        data = _render_xlsx(
            "数据",
            rows=[["项", "值"], ["A", 30], ["B", 70]],
            charts=[{"type": ctype, "categories": ["A", "B"], "values": [30, 70]}],
        )
        assert isinstance(data, bytes) and len(data) > 0
