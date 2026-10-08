"""文档级 ACL 越权评测集（回归门禁）。

场景：
  部门树 D1 > D2；用户 u_in∈D2（应继承 D1 授权）、u_out 无关。
  KB 为 internal；三份文档：inherit / public / restricted。
  restricted 文档 ACL：allow=dept(D1)，deny=user(u_out)。

断言：
  - u_in 能命中 restricted（部门向下继承生效）
  - u_out 对 restricted 的命中集合为空（越权拦截，复现率 0）
  - u_out 仍能命中 inherit/public
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import (
    VIS_KB_DEFAULT,
    VIS_KB_PUBLIC,
    VIS_RESTRICTED,
    Chunk,
    Department,
    Document,
    KBMember,
    KnowledgeBase,
    Tenant,
    User,
)
from app.providers.drivers.local_hash import LocalHashDriver
from app.services.permission import (
    PrincipalSet,
    dept_principal,
    user_principal,
)
from app.services.retrieval_service import retrieve

DIM = 64


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        tenant = Tenant(name="T", slug="t1")
        db.add(tenant)
        await db.flush()

        d1 = Department(tenant_id=tenant.id, name="D1", parent_id=None, path="", depth=0)
        db.add(d1)
        await db.flush()
        d1.path = f"{d1.id}."
        d2 = Department(tenant_id=tenant.id, name="D2", parent_id=d1.id, path="", depth=1)
        db.add(d2)
        await db.flush()
        d2.path = f"{d1.id}.{d2.id}."

        u_in = User(
            tenant_id=tenant.id, username="u_in", password_hash=hash_password("x"),
            department_id=d2.id, display_name="in",
        )
        u_out = User(
            tenant_id=tenant.id, username="u_out", password_hash=hash_password("x"),
            display_name="out",
        )
        db.add_all([u_in, u_out])
        await db.flush()

        kb = KnowledgeBase(
            tenant_id=tenant.id, name="KB", visibility="internal",
            embedding_dim=DIM, owner_id=u_in.id,
        )
        db.add(kb)
        await db.flush()
        # 两个用户都是 KB 成员（隔离出"文档级 ACL"这一层，避免全空假阳性）
        db.add_all([
            KBMember(tenant_id=tenant.id, kb_id=kb.id, principal_id=user_principal(u_in.id), perm_level="viewer"),
            KBMember(tenant_id=tenant.id, kb_id=kb.id, principal_id=user_principal(u_out.id), perm_level="viewer"),
        ])
        await db.flush()

        # 三份文档
        docs = {}
        for key, vis, vs in (
            ("inherit", "inherit", VIS_KB_DEFAULT),
            ("public", "public", VIS_KB_PUBLIC),
            ("restricted", "restricted", VIS_RESTRICTED),
        ):
            d = Document(tenant_id=tenant.id, kb_id=kb.id, title=key, visibility=vis, status="ready")
            db.add(d)
            await db.flush()
            docs[key] = d

            chunk_content = f"{key} 文档的独有内容 unique_{key}_token"
            c = Chunk(
                tenant_id=tenant.id, kb_id=kb.id, doc_id=d.id, ordinal=0,
                chunk_type="flat", content=chunk_content, token_count=10,
                vis_scope=vs,
                acl_allow=[dept_principal(d1.id)] if key == "restricted" else None,
                acl_deny=[user_principal(u_out.id)] if key == "restricted" else None,
                enabled=True,
            )
            drv = LocalHashDriver(dim=DIM)
            c.embedding = (await drv.embed([chunk_content]))[0]
            db.add(c)

        await db.commit()
        return {
            "tenant_id": tenant.id, "d1": d1.id, "d2": d2.id,
            "u_in": u_in.id, "u_out": u_out.id, "kb": kb.id,
            "doc_inherit": docs["inherit"].id,
            "doc_public": docs["public"].id,
            "doc_restricted": docs["restricted"].id,
        }


@pytest.fixture(scope="module")
def data():
    return asyncio.get_event_loop().run_until_complete(_setup())


def _ps_in(d) -> PrincipalSet:
    """u_in 在 D2，principal 含 D2 与祖先 D1。"""
    return PrincipalSet(
        user_id=d["u_in"], tenant_id=d["tenant_id"], dept_ids=[d["d1"], d["d2"]],
    )


def _ps_out(d) -> PrincipalSet:
    return PrincipalSet(user_id=d["u_out"], tenant_id=d["tenant_id"], dept_ids=[])


async def _search(ps: PrincipalSet, query: str):
    async with AsyncSessionLocal() as db:
        resp = await retrieve(db, ps=ps, query=query, top_k=10, use_hybrid=True)
        return {c.doc_id for c in resp.chunks}


@pytest.mark.asyncio
async def test_inherit_doc_visible_to_all(data):
    assert data["doc_inherit"] in await _search(_ps_in(data), "unique_inherit_token")
    assert data["doc_inherit"] in await _search(_ps_out(data), "unique_inherit_token")


@pytest.mark.asyncio
async def test_public_doc_visible_to_all(data):
    assert data["doc_public"] in await _search(_ps_in(data), "unique_public_token")
    assert data["doc_public"] in await _search(_ps_out(data), "unique_public_token")


@pytest.mark.asyncio
async def test_restricted_dept_inheritance(data):
    """u_in∈D2 应通过 D1 授权命中受限文档。"""
    hit = await _search(_ps_in(data), "unique_restricted_token")
    assert data["doc_restricted"] in hit, "部门向下继承失效"


@pytest.mark.asyncio
async def test_restricted_denied_for_outsider(data):
    """u_out 对受限文档复现率必须为 0。"""
    hit = await _search(_ps_out(data), "unique_restricted_token")
    assert data["doc_restricted"] not in hit, "越权：无关用户召回了受限文档"


@pytest.mark.asyncio
async def test_no_leak_across_all_queries(data):
    """广度回归：u_out 的任何查询都不得命中受限文档。"""
    for q in ("unique_restricted_token", "文档 独有 内容", "restricted 文档"):
        hit = await _search(_ps_out(data), q)
        assert data["doc_restricted"] not in hit, f"越权复现: query={q}"
