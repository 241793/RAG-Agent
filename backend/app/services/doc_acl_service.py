"""文档级 ACL 服务：把 DocumentACL 落到 chunk 的权限元数据。

设计要点：
- ACL 存的是 principal（部门/角色/用户/组 id），不是解析后的用户。
  因此 KB 成员变动、部门/角色/组成员变动都无需重刷 chunk；只有
  「文档 visibility 变更」或「DocumentACL 行增删」才需重算，且只重算该文档。
- 与 permission.build_doc_acl_clause 的查询期语义一一对应。
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    VIS_KB_DEFAULT,
    VIS_KB_PUBLIC,
    VIS_RESTRICTED,
    Chunk,
    Document,
    DocumentACL,
    KnowledgeBase,
)


def doc_vis_scope(kb: KnowledgeBase | None, doc: Document) -> int:
    """根据文档与知识库可见性决定 chunk 的 vis_scope。"""
    if doc.visibility == "restricted":
        return VIS_RESTRICTED
    if doc.visibility == "public" or (kb and kb.visibility == "public"):
        return VIS_KB_PUBLIC
    return VIS_KB_DEFAULT


async def load_doc_acl(db: AsyncSession, doc_id: int) -> tuple[list[int], list[int]]:
    """返回 (allow_principals, deny_principals)。"""
    rows = (
        await db.execute(select(DocumentACL).where(DocumentACL.document_id == doc_id))
    ).scalars().all()
    allow = [r.principal_id for r in rows if r.effect == "allow"]
    deny = [r.principal_id for r in rows if r.effect == "deny"]
    return allow, deny


async def recompute_doc_acl(db: AsyncSession, doc_id: int) -> None:
    """重算某文档所有 chunk 的 vis_scope 与 acl_allow/acl_deny。

    代价 O(该文档 chunk 数)，有界。文档 visibility 变更或 ACL 增删后调用。
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        return
    kb = await db.get(KnowledgeBase, doc.kb_id)
    vis = doc_vis_scope(kb, doc)
    if vis == VIS_RESTRICTED:
        allow, deny = await load_doc_acl(db, doc_id)
        values = {"vis_scope": VIS_RESTRICTED, "acl_allow": allow, "acl_deny": deny}
    else:
        values = {"vis_scope": vis, "acl_allow": None, "acl_deny": None}
    await db.execute(update(Chunk).where(Chunk.doc_id == doc_id).values(**values))


async def build_chunk_acl_fields(db: AsyncSession, kb, doc: Document) -> dict:
    """入库时构造 chunk 的权限字段。"""
    vis = doc_vis_scope(kb, doc)
    if vis == VIS_RESTRICTED:
        allow, deny = await load_doc_acl(db, doc.id)
        return {"vis_scope": vis, "acl_allow": allow, "acl_deny": deny}
    return {"vis_scope": vis, "acl_allow": None, "acl_deny": None}
