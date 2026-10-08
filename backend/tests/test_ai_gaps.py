"""AI 工具缺口补齐：文档分块编辑、文件库管理、技能脚本试跑、Provider 测试、KB 统计。"""
from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import func, select

from app.agents.tools.base import ToolContext
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Agent, Artifact, Chunk, Document, KnowledgeBase, Skill, SkillPackage, Tenant, User
from app.services.permission import PrincipalSet


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "gap"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="GAP", slug="gap"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "gap_admin"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="gap_admin", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "gap_kb"))).scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name="gap_kb", visibility="public", embedding_dim=64, owner_id=u.id)
            db.add(kb); await db.flush()
        doc = (await db.execute(select(Document).where(Document.title == "gap_doc"))).scalar_one_or_none()
        if not doc:
            doc = Document(tenant_id=t.id, kb_id=kb.id, title="gap_doc", source_type="upload",
                           content_hash="h", status="ready", uploaded_by=u.id)
            db.add(doc); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id, "kb_id": kb.id, "doc_id": doc.id}


def _ctx(db, d):
    return ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                       tenant_id=d["tenant_id"], user_id=d["user_id"])


# ---- manage_doc_chunk ----
def test_manage_doc_chunk_list_and_delete():
    from app.agents.tools.ops_tools2 import ManageDocChunkTool

    async def _run():
        d = await _setup()
        tool = ManageDocChunkTool()
        async with AsyncSessionLocal() as db:
            c1 = Chunk(tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=d["doc_id"], ordinal=0,
                       chunk_type="flat", content="第一个分块的内容", token_count=8)
            c2 = Chunk(tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=d["doc_id"], ordinal=1,
                       chunk_type="flat", content="第二个分块", token_count=5)
            db.add_all([c1, c2]); await db.commit()
            c1id, c2id = c1.id, c2.id
        async with AsyncSessionLocal() as db:
            r = await tool.run({"action": "list", "doc_id": d["doc_id"]}, _ctx(db, d))
            assert not r.is_error and "第一个分块" in r.content
        async with AsyncSessionLocal() as db:
            r2 = await tool.run({"action": "delete", "doc_id": d["doc_id"], "chunk_id": c1id}, _ctx(db, d))
            await db.commit()
            assert not r2.is_error
        async with AsyncSessionLocal() as db:
            cnt = (await db.execute(select(func.count()).select_from(Chunk).where(Chunk.doc_id == d["doc_id"]))).scalar_one()
            assert cnt == 1
    asyncio.new_event_loop().run_until_complete(_run())


def test_manage_doc_chunk_update():
    from app.agents.tools.ops_tools2 import ManageDocChunkTool

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            c = Chunk(tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=d["doc_id"], ordinal=9,
                      chunk_type="flat", content="旧内容", token_count=3)
            db.add(c); await db.commit(); cid = c.id
        async with AsyncSessionLocal() as db:
            r = await ManageDocChunkTool().run(
                {"action": "update", "doc_id": d["doc_id"], "chunk_id": cid, "content": "新内容 abc"}, _ctx(db, d))
            await db.commit()
            assert not r.is_error
        async with AsyncSessionLocal() as db:
            c = await db.get(Chunk, cid)
            assert c.content == "新内容 abc"
    asyncio.new_event_loop().run_until_complete(_run())


def test_manage_doc_chunk_split():
    from app.agents.tools.ops_tools2 import ManageDocChunkTool

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            c = Chunk(tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=d["doc_id"], ordinal=50,
                      chunk_type="flat", content="AAAABBBB", token_count=8)
            db.add(c); await db.commit(); cid = c.id
        async with AsyncSessionLocal() as db:
            r = await ManageDocChunkTool().run(
                {"action": "split", "doc_id": d["doc_id"], "chunk_id": cid, "offset": 4}, _ctx(db, d))
            await db.commit()
            assert not r.is_error
        async with AsyncSessionLocal() as db:
            cs = (await db.execute(select(Chunk).where(Chunk.doc_id == d["doc_id"], Chunk.ordinal >= 50).order_by(Chunk.ordinal))).scalars().all()
            texts = [x.content for x in cs]
            assert "AAAA" in texts and "BBBB" in texts
    asyncio.new_event_loop().run_until_complete(_run())


# ---- manage_files ----
def test_manage_files_list_delete():
    from app.agents.tools.ops_tools2 import ManageFilesTool

    async def _run():
        d = await _setup()
        tool = ManageFilesTool()
        async with AsyncSessionLocal() as db:
            a = Artifact(tenant_id=d["tenant_id"], user_id=d["user_id"], file_key="k/x.txt",
                         file_name="报告.txt", file_ext="txt", size=1234, source="generated")
            db.add(a); await db.commit(); aid = a.id
        async with AsyncSessionLocal() as db:
            r = await tool.run({"action": "list", "keyword": "报告"}, _ctx(db, d))
            assert not r.is_error and "报告.txt" in r.content
        async with AsyncSessionLocal() as db:
            r2 = await tool.run({"action": "delete", "artifact_id": aid}, _ctx(db, d))
            await db.commit()
            assert not r2.is_error
        async with AsyncSessionLocal() as db:
            assert await db.get(Artifact, aid) is None
    asyncio.new_event_loop().run_until_complete(_run())


def test_manage_files_cleanup_expired():
    from app.agents.tools.ops_tools2 import ManageFilesTool

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            old = Artifact(tenant_id=d["tenant_id"], user_id=d["user_id"], file_key="k/old.txt",
                           file_name="old.txt", size=1, source="generated",
                           expires_at=int(time.time() * 1000) - 10000)
            fresh = Artifact(tenant_id=d["tenant_id"], user_id=d["user_id"], file_key="k/new.txt",
                             file_name="new.txt", size=1, source="generated",
                             expires_at=int(time.time() * 1000) + 100000)
            db.add_all([old, fresh]); await db.commit()
            oldid, freshid = old.id, fresh.id
        async with AsyncSessionLocal() as db:
            r = await ManageFilesTool().run({"action": "cleanup"}, _ctx(db, d))
            await db.commit()
            assert not r.is_error and "1" in r.content
        async with AsyncSessionLocal() as db:
            assert await db.get(Artifact, oldid) is None
            assert await db.get(Artifact, freshid) is not None
    asyncio.new_event_loop().run_until_complete(_run())


# ---- run_skill_script ----
def test_run_skill_script_disabled_and_whitelist(tmp_path, monkeypatch):
    from app.agents.tools.ops_tools2 import RunSkillScriptTool
    from app.core.config import settings

    async def _run():
        d = await _setup()
        monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
        async with AsyncSessionLocal() as db:
            sk = Skill(tenant_id=d["tenant_id"], owner_id=d["user_id"], name="s", slug="gap-s",
                       kind="prompt_pack", source="package")
            db.add(sk); await db.flush()
            pkg = SkillPackage(tenant_id=d["tenant_id"], skill_id=sk.id, name="s", source_type="zip",
                               pack_dir="1/p", entry_scripts=[{"name": "echo", "path": "echo.py"}],
                               scripts_enabled=False)
            db.add(pkg); await db.commit(); sid = sk.id
        # 未启用脚本 → 拒绝
        async with AsyncSessionLocal() as db:
            r = await RunSkillScriptTool().run({"skill_id": sid, "script": "echo"}, _ctx(db, d))
            assert r.is_error and "未启用" in r.content
        # 启用后，脚本名不在白名单 → 拒绝
        async with AsyncSessionLocal() as db:
            pkg = (await db.execute(select(SkillPackage).where(SkillPackage.skill_id == sid))).scalars().first()
            pkg.scripts_enabled = True
            await db.commit()
        async with AsyncSessionLocal() as db:
            r2 = await RunSkillScriptTool().run({"skill_id": sid, "script": "nope"}, _ctx(db, d))
            assert r2.is_error and "白名单" in r2.content
        # 白名单内 + 真实脚本 → 执行
        pack = tmp_path / "skills" / "1" / "p"
        pack.mkdir(parents=True)
        (pack / "echo.py").write_text(
            "import sys, json\nprint(json.dumps({'echo': (json.loads(sys.stdin.read() or '{}')).get('x')}))\n",
            encoding="utf-8")
        async with AsyncSessionLocal() as db:
            r3 = await RunSkillScriptTool().run(
                {"skill_id": sid, "script": "echo", "args": {"x": 7}}, _ctx(db, d))
            assert not r3.is_error and '"echo": 7' in r3.content
    asyncio.new_event_loop().run_until_complete(_run())


# ---- query_kb_stats ----
def test_query_kb_stats():
    from app.agents.tools.ops_tools2 import QueryKbStatsTool

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            db.add(Chunk(tenant_id=d["tenant_id"], kb_id=d["kb_id"], doc_id=d["doc_id"], ordinal=900,
                         chunk_type="flat", content="x", token_count=1))
            await db.commit()
        async with AsyncSessionLocal() as db:
            r = await QueryKbStatsTool().run({"kb_id": d["kb_id"]}, _ctx(db, d))
            assert not r.is_error and "统计" in r.content
            assert isinstance(r.data.get("chunks"), int)
    asyncio.new_event_loop().run_until_complete(_run())


# ---- test_provider（找不到 Provider 时的错误路径）----
def test_test_provider_not_found():
    from app.agents.tools.ops_tools2 import TestProviderTool

    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await TestProviderTool().run({"action": "health", "provider_id": 999999}, _ctx(db, d))
            assert r.is_error and "不存在" in r.content
    asyncio.new_event_loop().run_until_complete(_run())


# ---- 工具元数据 ----
def test_new_tools_metadata():
    from app.agents.tools.registry import registry

    expects = {
        "manage_doc_chunk": ("doc:update", "write"),
        "manage_files": ("file:manage", "write"),
        "run_skill_script": ("skill:execute", "write"),
        "test_provider": ("model:read", "write"),
        "query_kb_stats": ("kb:read", "read"),
    }
    for name, (perm, kind) in expects.items():
        t = registry.get_admin(name)
        assert t is not None, name
        assert t.required_permission == perm
        assert t.kind == kind
