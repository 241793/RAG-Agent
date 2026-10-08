"""知识库内容巡检：找出需要治理的文档（空/失败/无分块/未标签），供运营补内容。"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, RetrievalMiss


def _doc_brief(d: Document) -> dict:
    return {"id": d.id, "title": d.title, "kind": d.kind, "status": d.status,
            "char_count": d.char_count, "chunk_count": d.chunk_count}


async def audit_kb(db: AsyncSession, *, kb_id: int, tenant_id: int, stale_days: int = 180) -> dict:
    """巡检一个知识库，返回各类问题文档列表。"""
    rows = (await db.execute(
        select(Document).where(
            Document.tenant_id == tenant_id, Document.kb_id == kb_id, Document.status != "deleted",
        )
    )).scalars().all()

    empty: list[dict] = []
    failed: list[dict] = []
    no_chunk: list[dict] = []
    untagged: list[dict] = []
    stale: list[dict] = []
    cutoff = int((time.time() - stale_days * 86400) * 1000)

    for d in rows:
        if d.status == "failed":
            failed.append({**_doc_brief(d), "error": (d.error_msg or "")[:200]})
            continue
        if d.char_count == 0:
            empty.append(_doc_brief(d))
        if d.status == "ready" and d.chunk_count == 0:
            no_chunk.append(_doc_brief(d))
        if not d.tags:
            untagged.append(_doc_brief(d))
        # 陈旧：创建/更新时间早于 cutoff（updated_at 是 datetime）
        try:
            ts = int(d.updated_at.timestamp() * 1000) if d.updated_at else 0
        except Exception:  # noqa: BLE001
            ts = 0
        if ts and ts < cutoff:
            stale.append(_doc_brief(d))

    return {
        "total": len(rows),
        "empty": empty, "failed": failed, "no_chunk": no_chunk,
        "untagged": untagged, "stale": stale,
        "counts": {"empty": len(empty), "failed": len(failed), "no_chunk": len(no_chunk),
                   "untagged": len(untagged), "stale": len(stale)},
    }


async def top_missed_queries(db: AsyncSession, *, tenant_id: int, days: int = 30, limit: int = 20) -> list[dict]:
    """最近 N 天未命中的高频 query（按 query 聚合计数）。"""
    from sqlalchemy import func

    since = int((time.time() - days * 86400) * 1000)
    rows = (await db.execute(
        select(RetrievalMiss.query, func.count().label("n"))
        .where(RetrievalMiss.tenant_id == tenant_id, RetrievalMiss.created_at >= since)
        .group_by(RetrievalMiss.query)
        .order_by(func.count().desc())
        .limit(limit)
    )).all()
    return [{"query": q, "count": int(n)} for q, n in rows]
