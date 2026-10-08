"""图文知识条目测试：entry 入库跳过解析、检索带附件、命中媒体收集、CRUD 端点。"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.ingest.storage import get_storage
from app.models import Chunk, Document, KnowledgeBase, Tenant, User


@pytest.fixture(autouse=True)
def _mock_embedding(monkeypatch):
    """用本地确定性向量驱动替换 embedding，避免测试依赖上游模型配置。"""
    import app.tasks.ingest_tasks as it
    from app.providers.drivers.local_hash import LocalHashDriver

    class _RM:
        model_name = "local_hash"

    async def _fake_get_embedding(db, *, tenant_id, config_id=None):
        return LocalHashDriver(dim=64), _RM()

    monkeypatch.setattr(it, "get_embedding", _fake_get_embedding)


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "kbentry"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="KBENTRY", slug="kbentry"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "kbentry_admin"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="kbentry_admin", password_hash=hash_password("x"),
                     is_admin=True, display_name="管理员", user_type="internal")
            db.add(u); await db.flush()
        kb = KnowledgeBase(tenant_id=t.id, name="entry库", visibility="public", owner_id=u.id)
        db.add(kb); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id, "kb_id": kb.id}


async def _cleanup(db, doc_id: int, kb_id: int):
    from sqlalchemy import delete
    await db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    d = await db.get(Document, doc_id)
    if d:
        await db.delete(d)
    k = await db.get(KnowledgeBase, kb_id)
    if k:
        await db.delete(k)
    await db.commit()


def test_entry_ingest_skips_file_parse():
    """kind=entry：不解析文件，直接用 content 分块并置 ready。"""
    async def _run():
        d = await _setup()
        from app.tasks.ingest_tasks import process_document

        async with AsyncSessionLocal() as db:
            doc = Document(tenant_id=d["tenant_id"], kb_id=d["kb_id"], title="重置密码",
                           kind="entry", content="如何重置密码：设置-安全-修改密码。",
                           status="pending", uploaded_by=d["uid"])
            db.add(doc); await db.commit(); doc_id = doc.id
        await process_document(doc_id)
        async with AsyncSessionLocal() as db:
            dd = await db.get(Document, doc_id)
            chunks = (await db.execute(select(Chunk).where(Chunk.doc_id == doc_id))).scalars().all()
            assert dd.status == "ready"
            assert dd.char_count > 0
            assert chunks, "entry 应产生分块"
            assert "重置密码" in chunks[0].content
            await _cleanup(db, doc_id, d["kb_id"])
    asyncio.new_event_loop().run_until_complete(_run())


def test_entry_empty_content_fails():
    async def _run():
        d = await _setup()
        from app.tasks.ingest_tasks import process_document

        async with AsyncSessionLocal() as db:
            doc = Document(tenant_id=d["tenant_id"], kb_id=d["kb_id"], title="空",
                           kind="entry", content="   ", status="pending", uploaded_by=d["uid"])
            db.add(doc); await db.commit(); doc_id = doc.id
        await process_document(doc_id)
        async with AsyncSessionLocal() as db:
            dd = await db.get(Document, doc_id)
            assert dd.status == "failed"
            assert dd.error_msg, "应记录失败原因"
            await _cleanup(db, doc_id, d["kb_id"])
    asyncio.new_event_loop().run_until_complete(_run())


def test_retrieval_carries_attachments():
    async def _run():
        d = await _setup()
        from app.services.permission import PrincipalSet
        from app.services.retrieval_service import retrieve, to_citations
        from app.tasks.ingest_tasks import process_document

        async with AsyncSessionLocal() as db:
            doc = Document(tenant_id=d["tenant_id"], kb_id=d["kb_id"], title="退款流程",
                           kind="entry", content="退款流程说明：在订单页点申请退款，3 个工作日到账。",
                           attachments=[{"file_key": "x/y.png", "name": "退款截图.png",
                                         "mime": "image/png", "size": 100}],
                           status="pending", uploaded_by=d["uid"])
            db.add(doc); await db.commit(); doc_id = doc.id
        await process_document(doc_id)
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tenant_id"], is_admin=True)
            resp = await retrieve(db, ps=ps, query="怎么退款", kb_ids=[d["kb_id"]], top_k=5)
            assert resp.chunks, "应命中 entry 分块"
            hit = resp.chunks[0]
            assert hit.attachments, "检索结果应带出配套附件"
            assert hit.attachments[0]["name"] == "退款截图.png"
            cits = to_citations(resp.chunks)
            assert any(c.attachments for c in cits)
            await _cleanup(db, doc_id, d["kb_id"])
    asyncio.new_event_loop().run_until_complete(_run())


def test_collect_citation_media_reads_storage():
    """_collect_citation_media：从 storage 读附件、按 file_key 去重、限量。"""
    async def _run():
        d = await _setup()
        from app.channels.dispatcher import _collect_citation_media

        storage = get_storage()
        key, _ = storage.save(tenant_id=d["tenant_id"], filename="a.png", data=b"IMG-DATA")
        cits = [
            {"attachments": [{"file_key": key, "name": "a.png", "mime": "image/png"}]},
            {"attachments": [{"file_key": key, "name": "a.png", "mime": "image/png"}]},  # 重复
            {"attachments": [{"file_key": "missing", "name": "x", "mime": "image/png"}]},  # 读不到
        ]
        media = _collect_citation_media(cits)
        assert len(media) == 1, "按 file_key 去重、读不到的跳过"
        assert media[0]["type"] == "image" and media[0]["data"] == b"IMG-DATA"
        storage.delete(key)
        async with AsyncSessionLocal() as db:
            await _cleanup(db, 0, d["kb_id"])
    asyncio.new_event_loop().run_until_complete(_run())


def test_entry_endpoints_registered():
    import app.api.v1.document as doc
    paths = {r.path for r in doc.router.routes}
    assert "/documents/kbs/{kb_id}/entries" in paths
    assert "/documents/{doc_id}/entry" in paths
    assert "/documents/{doc_id}/attachments" in paths
    assert "/documents/{doc_id}/attachments/{idx}" in paths
    assert "/documents/{doc_id}/attachments/{idx}/download" in paths


def test_entry_type_kb_is_creatable_and_searchable():
    """source_type='entry' 的图文知识库：可建、可被检索（走本地向量/BM25）。"""
    async def _run():
        d = await _setup()
        from app.services.permission import PrincipalSet
        from app.services.retrieval_service import resolve_accessible_kbs, retrieve
        from app.tasks.ingest_tasks import process_document

        async with AsyncSessionLocal() as db:
            kb = KnowledgeBase(tenant_id=d["tenant_id"], name="图文库", visibility="public",
                               source_type="entry", owner_id=d["uid"])
            db.add(kb); await db.flush()
            doc = Document(tenant_id=d["tenant_id"], kb_id=kb.id, title="如何退货",
                           kind="entry", content="退货流程：在订单页申请退货，填写原因，客服审核后上门取件。",
                           status="pending", uploaded_by=d["uid"])
            db.add(doc); await db.commit()
            kb_id, doc_id = kb.id, doc.id
        # 入库
        await process_document(doc_id)
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tenant_id"], is_admin=True)
            ids = await resolve_accessible_kbs(db, ps)
            assert kb_id in ids, "图文库应可被访问检索"
            resp = await retrieve(db, ps=ps, query="怎么退货", kb_ids=[kb_id], top_k=5)
            assert resp.chunks, "图文库内容应可被检索命中"
            await _cleanup(db, doc_id, kb_id)
    asyncio.new_event_loop().run_until_complete(_run())


def test_entry_kb_skips_embedding_no_warning():
    """图文库（source_type=entry）入库不应调用向量模型，也不产生降级警告。"""
    async def _run():
        d = await _setup()
        from app.tasks.ingest_tasks import process_document

        async with AsyncSessionLocal() as db:
            kb = KnowledgeBase(tenant_id=d["tenant_id"], name="无向量库", visibility="public",
                               source_type="entry", owner_id=d["uid"])
            db.add(kb); await db.flush()
            doc = Document(tenant_id=d["tenant_id"], kb_id=kb.id, title="发票", kind="entry",
                           content="申请开发票：订单页点申请发票，填抬头税号即可。",
                           status="pending", uploaded_by=d["uid"])
            db.add(doc); await db.commit()
            kb_id, doc_id = kb.id, doc.id
        await process_document(doc_id)
        async with AsyncSessionLocal() as db:
            dd = await db.get(Document, doc_id)
            assert dd.status == "ready"
            assert not dd.error_msg, "图文库不应有降级警告"
            chunks = (await db.execute(select(Chunk).where(Chunk.doc_id == doc_id))).scalars().all()
            assert chunks, "应有分块"
            assert not any(c.embedding for c in chunks), "图文库不应写入向量"
            await _cleanup(db, doc_id, kb_id)
    asyncio.new_event_loop().run_until_complete(_run())
