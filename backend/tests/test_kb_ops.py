"""知识库运营面测试：visibility 语义、成员 principal 编码、stats 聚合、去重。

策略：visibility/成员用纯函数级（filter_accessible_kbs）+ DB 级组合验证；
stats 与分块编辑走 DB 级聚合断言，避免依赖 HTTP 层与鉴权中间件。
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import (
    Chunk,
    Department,
    Document,
    KBMember,
    KnowledgeBase,
    Tenant,
    User,
)
from app.services.permission import (
    PrincipalSet,
    dept_principal,
    filter_accessible_kbs,
    role_principal,
    user_principal,
)


# ---- 纯函数：visibility 三值语义 ----
def test_filter_visibility_semantics():
    ps = PrincipalSet(user_id=7, tenant_id=1, dept_ids=[], role_ids=[], group_ids=[])
    rows = [
        {"kb_id": 1, "visibility": "public", "principals": []},
        {"kb_id": 2, "visibility": "internal", "principals": []},
        {"kb_id": 3, "visibility": "private", "principals": []},
    ]
    # 非成员：public/internal 可见，private 不可见
    got = set(filter_accessible_kbs(ps, rows))
    assert got == {1, 2}


def test_filter_private_member_visible():
    ps = PrincipalSet(user_id=7, tenant_id=1, dept_ids=[5], role_ids=[], group_ids=[])
    rows = [
        {"kb_id": 3, "visibility": "private", "principals": [user_principal(7)]},
        {"kb_id": 4, "visibility": "private", "principals": [dept_principal(5)]},
        {"kb_id": 5, "visibility": "private", "principals": [user_principal(999)]},
    ]
    got = set(filter_accessible_kbs(ps, rows))
    assert got == {3, 4}


def test_filter_admin_bypass():
    ps = PrincipalSet(user_id=7, tenant_id=1, is_admin=True)
    rows = [{"kb_id": 9, "visibility": "private", "principals": []}]
    assert filter_accessible_kbs(ps, rows) == [9]


def test_principal_encoding_distinct():
    # 用户/部门/角色 编码互不冲突
    assert user_principal(1) != dept_principal(1) != role_principal(1)
    assert dept_principal(1) - user_principal(1) > 0


# ---- DB 级：stats 聚合 + 分块编辑/去重 ----
async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        tenant = Tenant(name="T2", slug="t2")
        db.add(tenant)
        await db.flush()
        u = User(
            tenant_id=tenant.id, username="kbu", password_hash=hash_password("x"),
            display_name="kbu",
        )
        db.add(u)
        await db.flush()
        kb = KnowledgeBase(
            tenant_id=tenant.id, name="OpsKB", visibility="private",
            embedding_dim=64, owner_id=u.id,
        )
        db.add(kb)
        await db.flush()

        # 两份文档：一份 ready pdf、一份 failed txt
        d1 = Document(
            tenant_id=tenant.id, kb_id=kb.id, title="A", file_ext="pdf",
            file_size=2048, status="ready", content_hash="hash-a", visibility="inherit",
        )
        d2 = Document(
            tenant_id=tenant.id, kb_id=kb.id, title="B", file_ext="txt",
            file_size=1024, status="failed", content_hash="hash-b", visibility="inherit",
        )
        db.add_all([d1, d2])
        await db.flush()

        # 分块：3 个，2 个有向量
        for i, has_vec in enumerate([True, True, False]):
            c = Chunk(
                tenant_id=tenant.id, kb_id=kb.id, doc_id=d1.id, ordinal=i,
                chunk_type="flat", content=f"内容{i}", token_count=3, enabled=True,
            )
            if has_vec:
                c.embedding = [0.1] * 64
            db.add(c)
        await db.commit()
        return {"tenant_id": tenant.id, "user": u.id, "kb": kb.id, "d1": d1.id}


@pytest.fixture(scope="module")
def kbdata():
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_setup())
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_stats_aggregate(kbdata):
    """stats 端点核心聚合：按 status/ext 分组、存储总和、向量覆盖率。"""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Document.status, Document.file_ext, Document.file_size)
                .where(Document.kb_id == kbdata["kb"])
            )
        ).all()
        by_status: dict[str, int] = {}
        by_ext: dict[str, int] = {}
        total_size = 0
        for status, ext, size in rows:
            by_status[status] = by_status.get(status, 0) + 1
            by_ext[(ext or "其它").lower()] = by_ext.get((ext or "其它").lower(), 0) + 1
            total_size += size
        assert by_status == {"ready": 1, "failed": 1}
        assert by_ext == {"pdf": 1, "txt": 1}
        assert total_size == 3072

        chunk_total = (
            await db.execute(select(func.count()).select_from(Chunk).where(Chunk.kb_id == kbdata["kb"]))
        ).scalar_one()
        embedded = (
            await db.execute(
                select(func.count()).select_from(Chunk).where(
                    Chunk.kb_id == kbdata["kb"], Chunk.embedding.is_not(None)
                )
            )
        ).scalar_one()
        assert chunk_total == 3
        assert embedded == 2


@pytest.mark.asyncio
async def test_chunk_edit_updates_content_and_count(kbdata):
    """分块内容更新 + chunk_count 一致。"""
    async with AsyncSessionLocal() as db:
        c = (
            await db.execute(select(Chunk).where(Chunk.doc_id == kbdata["d1"]).order_by(Chunk.ordinal))
        ).scalars().first()
        c.content = "改写后的内容 new_content"
        c.token_count = len(c.content)
        await db.commit()

        doc = await db.get(Document, kbdata["d1"])
        cnt = (
            await db.execute(select(func.count()).select_from(Chunk).where(Chunk.doc_id == doc.id))
        ).scalar_one()
        doc.chunk_count = int(cnt)
        await db.commit()
        assert doc.chunk_count == 3
        assert c.content == "改写后的内容 new_content"


@pytest.mark.asyncio
async def test_chunk_delete_reduces_count(kbdata):
    async with AsyncSessionLocal() as db:
        c = (
            await db.execute(select(Chunk).where(Chunk.doc_id == kbdata["d1"]).order_by(Chunk.ordinal))
        ).scalars().first()
        await db.delete(c)
        await db.commit()
        cnt = (
            await db.execute(
                select(func.count()).select_from(Chunk).where(Chunk.doc_id == kbdata["d1"])
            )
        ).scalar_one()
        assert cnt == 2


@pytest.mark.asyncio
async def test_content_hash_dedup_query(kbdata):
    """去重：按 (kb_id, content_hash) 命中同库已有文档。"""
    async with AsyncSessionLocal() as db:
        dup = (
            await db.execute(
                select(Document).where(
                    Document.kb_id == kbdata["kb"], Document.content_hash == "hash-a"
                ).limit(1)
            )
        ).scalar_one_or_none()
        assert dup is not None and dup.title == "A"
        none = (
            await db.execute(
                select(Document).where(
                    Document.kb_id == kbdata["kb"], Document.content_hash == "no-such"
                ).limit(1)
            )
        ).scalar_one_or_none()
        assert none is None


def test_kbupdate_schema_accepts_new_fields():
    """KBUpdate 接受 embedding_model_id / chunk_strategy / settings / tags 结构。"""
    from app.schemas.kb import KBUpdate, MemberIn

    m = KBUpdate(
        chunk_strategy={"type": "parent_child", "child_size": 400},
        embedding_model_id=5,
        settings={"x": 1},
    )
    assert m.chunk_strategy["type"] == "parent_child"
    assert m.embedding_model_id == 5
    assert m.settings == {"x": 1}

    mi = MemberIn(principal_type="department", principal_id=3, perm_level="editor")
    assert mi.principal_type == "department"


def test_new_endpoints_registered():
    """新增端点已挂到路由（防漏注册）。"""
    from app.api.v1.document import router as doc_router
    from app.api.v1.kb import router as kb_router

    kb_paths = {r.path for r in kb_router.routes}
    assert "/kbs/{kb_id}/stats" in kb_paths

    doc_paths = {r.path for r in doc_router.routes}
    for p in (
        "/documents/{doc_id}/raw",
        "/documents/{doc_id}/chunks/{chunk_id}",
        "/documents/{doc_id}/chunks/{chunk_id}/split",
        "/documents/batch-delete",
        "/documents/batch-move",
        "/documents/batch-visibility",
        "/documents/batch-reprocess",
        "/documents/{doc_id}/tags",
    ):
        assert p in doc_paths, f"端点未注册: {p}"
