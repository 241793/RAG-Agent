"""外部知识库「导入同步」服务。

与「联邦实时检索」（每次查询时按 connector 拉远端）不同，导入同步将远端内容
一次性拉取、切块、向量化并落库到本地索引（Document + Chunk），此后检索走本地，
不再依赖远端可用性，且可与本地内容一起混合检索/重排。

同步策略：
- 若连接器实现了 list_documents（批量列举），直接拉全量；
- 否则退化为「按种子查询检索导入」：用 KB 配置里的 seed_queries 逐条 search 收集。
- 幂等：以 (kb_id, source_uri 或 content_hash) 去重，重复同步不产生重复文档。
"""
from __future__ import annotations

import hashlib
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ConnectorDoc
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Document, KnowledgeBase

logger = get_logger("kb_sync")

# 导入同步在 KB.settings 里的配置键
SYNC_ENABLED = "sync_enabled"
SYNC_SEED_QUERIES = "sync_seed_queries"
SYNC_LAST_AT = "sync_last_at"
SYNC_LAST_STATUS = "sync_last_status"
SYNC_LAST_COUNT = "sync_last_count"
SYNC_LAST_ERROR = "sync_last_error"
SYNC_LIMIT = "sync_limit"


def _doc_hash(content: str, title: str | None) -> str:
    h = hashlib.sha256()
    h.update((title or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((content or "").encode("utf-8"))
    return h.hexdigest()


def _ext_ref_to_uri(kb_id: int, ext: ConnectorDoc) -> str:
    """外部片段的稳定标识：优先 source_uri，否则用 ref（如 kb3:12）。"""
    return ext.source_uri or ext.ref or f"kb{kb_id}:ext"


async def _collect_remote(conn, kb: KnowledgeBase, limit: int) -> list[ConnectorDoc]:
    """收集远端文档：批量列举优先，退化到种子查询。"""
    docs: list[ConnectorDoc] = []
    try:
        listed = await conn.list_documents(limit=limit)
        if listed:
            return listed[:limit]
    except NotImplementedError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("kb_sync_list_failed_fallback_to_search", kb_id=kb.id, err=str(e)[:200])

    seeds = (kb.settings or {}).get(SYNC_SEED_QUERIES) or []
    if isinstance(seeds, str):
        seeds = [s.strip() for s in seeds.splitlines() if s.strip()]
    for q in seeds:
        try:
            hits = await conn.search(str(q), top_k=min(limit, 100))
            docs.extend(hits)
        except Exception as e:  # noqa: BLE001
            logger.warning("kb_sync_seed_search_failed", kb_id=kb.id, query=str(q)[:80], err=str(e)[:200])
    return docs[:limit]


async def sync_external_kb(db: AsyncSession, kb_id: int, *, limit: int = 500) -> dict:
    """把外部知识库的内容导入本地索引。返回同步结果摘要。

    仅对 source_type=external 的 KB 生效。采用「先落 pending 文档 + 入库队列」的方式，
    切块与向量化复用既有入库流水线（process_document）。
    """
    from app.connectors.registry import from_kb

    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise NotFoundError("知识库不存在")
    if (kb.source_type or "local") != "external":
        raise ValidationError("仅外部知识库支持导入同步")

    conn = from_kb(kb)
    if conn is None:
        raise ValidationError("该知识库未配置可用连接器")

    settings = dict(kb.settings or {})
    limit = int(settings.get(SYNC_LIMIT) or limit)
    started = int(time.time() * 1000)
    try:
        remote = await _collect_remote(conn, kb, limit)
    except Exception as e:  # noqa: BLE001
        settings[SYNC_LAST_AT] = started
        settings[SYNC_LAST_STATUS] = "failed"
        settings[SYNC_LAST_ERROR] = str(e)[:500]
        kb.settings = settings
        await db.flush()
        raise

    # 现有文档的标识集合（source_uri 与 content_hash 双查重）
    existing = (
        await db.execute(
            select(Document.source_uri, Document.content_hash).where(
                Document.kb_id == kb_id, Document.source_type == "external_sync"
            )
        )
    ).all()
    seen_uris = {r[0] for r in existing if r[0]}
    seen_hashes = {r[1] for r in existing if r[1]}

    created: list[int] = []
    skipped = 0
    for ext in remote:
        content = (ext.content or "").strip()
        if not content:
            continue
        chash = _doc_hash(content, ext.title)
        uri = _ext_ref_to_uri(kb_id, ext)
        if uri in seen_uris or chash in seen_hashes:
            skipped += 1
            continue
        doc = Document(
            tenant_id=kb.tenant_id, kb_id=kb_id,
            title=(ext.title or content[:60]).strip()[:200],
            kind="file", source_type="external_sync",
            source_uri=uri, content=content, content_hash=chash,
            status="pending", progress=0,
        )
        db.add(doc)
        await db.flush()
        created.append(doc.id)
        seen_uris.add(uri)
        seen_hashes.add(chash)

    settings[SYNC_LAST_AT] = started
    settings[SYNC_LAST_STATUS] = "success"
    settings[SYNC_LAST_COUNT] = len(created)
    settings[SYNC_LAST_ERROR] = None
    kb.settings = settings
    await db.commit()

    # 入队切块+向量化（复用既有流水线）
    from app.tasks.ingest_tasks import enqueue_document

    for did in created:
        await enqueue_document(did)

    logger.info("kb_sync_done", kb_id=kb_id, fetched=len(remote), created=len(created), skipped=skipped)
    return {
        "kb_id": kb_id, "fetched": len(remote), "created": len(created),
        "skipped": skipped, "document_ids": created, "started_at": started,
    }


def sync_status(kb: KnowledgeBase) -> dict:
    """读取该库的同步状态摘要。"""
    s = kb.settings or {}
    return {
        "enabled": bool(s.get(SYNC_ENABLED)),
        "last_at": s.get(SYNC_LAST_AT),
        "last_status": s.get(SYNC_LAST_STATUS),
        "last_count": s.get(SYNC_LAST_COUNT),
        "last_error": s.get(SYNC_LAST_ERROR),
        "seed_queries": s.get(SYNC_SEED_QUERIES) or [],
        "limit": s.get(SYNC_LIMIT) or 500,
        "synced_doc_count": None,  # 由 API 层补（避免此函数查库）
    }
