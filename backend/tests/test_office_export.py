"""办公功能：会话导出（md/pdf/docx）、文档批量合并导出。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Chunk, Conversation, Document, KnowledgeBase, Message, Tenant, User


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "office"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="OFC", slug="office"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "ofc_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="ofc_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        conv = (await db.execute(select(Conversation).where(Conversation.title == "办公测试会话"))).scalar_one_or_none()
        if not conv:
            conv = Conversation(tenant_id=t.id, user_id=u.id, title="办公测试会话")
            db.add(conv); await db.flush()
            db.add(Message(tenant_id=t.id, conversation_id=conv.id, role="user", content="你好，帮我写周报", created_at=1))
            db.add(Message(tenant_id=t.id, conversation_id=conv.id, role="assistant", content="## 本周工作\n- 完成 A",
                           citations=[{"doc_title": "手册", "page": 3}], created_at=2))
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "ofc_kb"))).scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name="ofc_kb", visibility="public", embedding_dim=64, owner_id=u.id)
            db.add(kb); await db.flush()
        docs = []
        for i in range(2):
            d = (await db.execute(select(Document).where(Document.title == f"ofc_doc_{i}"))).scalar_one_or_none()
            if not d:
                d = Document(tenant_id=t.id, kb_id=kb.id, title=f"ofc_doc_{i}", source_type="upload",
                             content_hash=f"h{i}", status="ready", uploaded_by=u.id)
                db.add(d); await db.flush()
                db.add(Chunk(tenant_id=t.id, kb_id=kb.id, doc_id=d.id, ordinal=0, chunk_type="flat",
                             content=f"文档{i}的正文内容", token_count=8))
            docs.append(d.id)
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id, "conv_id": conv.id, "doc_ids": docs}


def test_export_markdown_contains_messages():
    from app.services.export_service import conversation_to_markdown, export_conversation

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, d["conv_id"])
            md = await conversation_to_markdown(db, conversation=conv, user_id=d["user_id"])
            assert "办公测试会话" in md and "帮我写周报" in md and "完成 A" in md
            assert "参考来源" in md and "手册" in md
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, d["conv_id"])
            fn, data, mime = await export_conversation(db, conversation=conv, user_id=d["user_id"], fmt="md")
            assert fn.endswith(".md") and "text/markdown" in mime and len(data) > 0
    asyncio.new_event_loop().run_until_complete(_run())


def test_export_pdf_and_docx():
    from app.services.export_service import export_conversation

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, d["conv_id"])
            fn, data, mime = await export_conversation(db, conversation=conv, user_id=d["user_id"], fmt="pdf")
            assert fn.endswith(".pdf") and data[:4] == b"%PDF"
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, d["conv_id"])
            fn2, data2, mime2 = await export_conversation(db, conversation=conv, user_id=d["user_id"], fmt="docx")
            assert fn2.endswith(".docx") and data2[:2] == b"PK"  # docx = zip
    asyncio.new_event_loop().run_until_complete(_run())


def test_documents_to_markdown_merge():
    from app.models import Document
    from app.services.export_service import documents_to_markdown

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            docs = (await db.execute(select(Document).where(Document.id.in_(d["doc_ids"])))).scalars().all()
            md = await documents_to_markdown(db, docs=list(docs))
            assert "文档合并导出" in md
            assert "文档0的正文内容" in md and "文档1的正文内容" in md
    asyncio.new_event_loop().run_until_complete(_run())


def test_export_endpoints_registered():
    from app.api.v1.chat import router as chat_router
    from app.api.v1.document import router as doc_router

    chat_paths = {r.path for r in chat_router.routes}
    assert any(p.endswith("/export") for p in chat_paths)
    assert any(p.endswith("/share") for p in chat_paths)
    doc_paths = {r.path for r in doc_router.routes}
    assert "/documents/batch-merge-export" in doc_paths
