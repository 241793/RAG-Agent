"""新 AI 工具：工作流运行/审批、邮件源、导出/分享、合并导出、系统设置。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.ops_tools2 import (
    ApproveWorkflowRunTool,
    ExportConversationTool,
    ManageEmailSourceTool,
    ManageSystemSettingsTool,
    MergeExportDocumentsTool,
    RunWorkflowTool,
)
from app.agents.tools.registry import registry
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Chunk, Conversation, Document, KnowledgeBase, Message, Tenant, User
from app.services.permission import PrincipalSet


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "ai2"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="AI2", slug="ai2"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "ai2_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="ai2_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "ai2_kb"))).scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name="ai2_kb", visibility="public", embedding_dim=64, owner_id=u.id)
            db.add(kb); await db.flush()
        conv = (await db.execute(select(Conversation).where(Conversation.title == "ai2_conv"))).scalar_one_or_none()
        if not conv:
            conv = Conversation(tenant_id=t.id, user_id=u.id, title="ai2_conv")
            db.add(conv); await db.flush()
            db.add(Message(tenant_id=t.id, conversation_id=conv.id, role="user", content="你好", created_at=1))
            db.add(Message(tenant_id=t.id, conversation_id=conv.id, role="assistant", content="你好呀", created_at=2))
        for i in range(2):
            d = (await db.execute(select(Document).where(Document.title == f"ai2_doc_{i}"))).scalar_one_or_none()
            if not d:
                d = Document(tenant_id=t.id, kb_id=kb.id, title=f"ai2_doc_{i}", source_type="upload",
                             content_hash=f"ai2h{i}", status="ready", uploaded_by=u.id)
                db.add(d); await db.flush()
                db.add(Chunk(tenant_id=t.id, kb_id=kb.id, doc_id=d.id, ordinal=0, chunk_type="flat",
                             content=f"文档{i}正文", token_count=4))
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id, "kb_id": kb.id, "conv_id": conv.id}


def _ctx(db, d):
    return ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                       tenant_id=d["tenant_id"], user_id=d["user_id"])


def test_new_tools_registered():
    expects = {
        "run_workflow": "workflow:run",
        "approve_workflow_run": "workflow:run",
        "manage_email_source": "kb:update",
        "export_conversation": "chat:use",
        "merge_export_documents": "doc:read",
        "manage_system_settings": "system:manage",
    }
    for name, perm in expects.items():
        t = registry.get_admin(name)
        assert t is not None, f"缺少工具 {name}"
        assert t.required_permission == perm


def test_export_conversation_share():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await ExportConversationTool().run({"conversation_id": d["conv_id"], "share": True}, _ctx(db, d))
            await db.commit()
            assert not r.is_error, r.content
            assert "分享链接" in r.content and r.data.get("url")
    asyncio.new_event_loop().run_until_complete(_run())


def test_export_conversation_file():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await ExportConversationTool().run({"conversation_id": d["conv_id"], "format": "docx"}, _ctx(db, d))
            await db.commit()
            assert not r.is_error
            assert r.data["name"].endswith(".docx") and r.data.get("artifact_id")
    asyncio.new_event_loop().run_until_complete(_run())


def test_merge_export_documents():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            docs = (await db.execute(select(Document).where(Document.kb_id == d["kb_id"]))).scalars().all()
            ids = [x.id for x in docs]
            r = await MergeExportDocumentsTool().run({"doc_ids": ids, "format": "md"}, _ctx(db, d))
            await db.commit()
            assert not r.is_error, r.content
            assert "合并" in r.content and r.data.get("artifact_id")
    asyncio.new_event_loop().run_until_complete(_run())


def test_manage_system_settings_get_and_update():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await ManageSystemSettingsTool().run({"action": "get"}, _ctx(db, d))
            assert not r.is_error and "retrieval_top_k" in r.content
        async with AsyncSessionLocal() as db:
            r2 = await ManageSystemSettingsTool().run(
                {"action": "update", "updates": {"retrieval_top_k": 7}}, _ctx(db, d))
            await db.commit()
            assert not r2.is_error and "retrieval_top_k" in r2.content
        from app.core.config import settings
        assert settings.retrieval_top_k == 7
    asyncio.new_event_loop().run_until_complete(_run())


def test_manage_email_source_crud():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            # 无 imap_host → 报错
            r0 = await ManageEmailSourceTool().run({"action": "create", "kb_id": d["kb_id"]}, _ctx(db, d))
            assert r0.is_error
        async with AsyncSessionLocal() as db:
            r = await ManageEmailSourceTool().run({
                "action": "create", "name": "测试邮箱", "imap_host": "imap.x.com",
                "username": "u@x.com", "password": "pwd", "kb_id": d["kb_id"],
            }, _ctx(db, d))
            await db.commit()
            assert not r.is_error and "已创建" in r.content
            sid = int(r.content.split("#")[1].split("「")[0])
        async with AsyncSessionLocal() as db:
            r2 = await ManageEmailSourceTool().run({"action": "list"}, _ctx(db, d))
            assert "测试邮箱" in r2.content
        async with AsyncSessionLocal() as db:
            r3 = await ManageEmailSourceTool().run({"action": "delete", "source_id": sid}, _ctx(db, d))
            await db.commit()
            assert not r3.is_error
    asyncio.new_event_loop().run_until_complete(_run())


def test_workflow_tool_missing_agent():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await RunWorkflowTool().run({"action": "run", "agent_id": 999999}, _ctx(db, d))
            assert r.is_error and "不存在" in r.content
    asyncio.new_event_loop().run_until_complete(_run())


def test_approve_tool_missing_run():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await ApproveWorkflowRunTool().run({"run_id": 999999}, _ctx(db, d))
            assert r.is_error and "不存在" in r.content
    asyncio.new_event_loop().run_until_complete(_run())
