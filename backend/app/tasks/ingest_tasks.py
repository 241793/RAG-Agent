"""文档入库流水线任务：parse → chunk → embed → finalize。"""
from __future__ import annotations

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.ingest.chunkers.chunker import chunk_text
from app.ingest.parsers.parser import parse_file
from app.ingest.storage import get_storage
from app.models import Chunk, Document, KnowledgeBase, VIS_KB_DEFAULT
from app.providers.registry import get_embedding
from app.retrieval.vector_store.store import get_vector_store
from app.tasks.queue import submit

logger = get_logger("ingest")

# 归档正文上限（字符）。避免历史版本无限膨胀；分块快照另存，回滚以快照为准。
_ARCHIVE_CONTENT_LIMIT = 200_000


async def _archive_version(db, doc: Document, reason: str = "reprocess") -> bool:
    """归档文档当前版本（正文 + 分块快照），供版本历史查看与回滚。

    仅在文档已有分块（即非首次入库）时归档；首次入库无旧版本，返回 False。
    """
    from sqlalchemy import select as _select

    from app.models import DocumentVersion

    old = (
        await db.execute(
            _select(Chunk).where(Chunk.doc_id == doc.id).order_by(Chunk.ordinal)
        )
    ).scalars().all()
    if not old:
        return False
    # ordinal → ordinal 的父指针还原（回滚时重建父子关系用）
    id_to_ordinal = {c.id: c.ordinal for c in old}
    snapshot = [
        {
            "ordinal": c.ordinal,
            "chunk_type": c.chunk_type,
            "content": c.content,
            "parent_content": c.parent_content,
            "parent_ordinal": id_to_ordinal.get(c.parent_id) if c.parent_id else None,
            "page": c.page,
            "section": c.section,
            "token_count": c.token_count,
        }
        for c in old
    ]
    # 正文：优先用 doc.content（图文条目），否则由分块拼回
    body = (doc.content or "").strip()
    if not body:
        body = "\n".join(c.content for c in old if c.chunk_type != "parent")
    ver = DocumentVersion(
        tenant_id=doc.tenant_id,
        doc_id=doc.id,
        version=doc.version or 1,
        title=doc.title,
        content=body[:_ARCHIVE_CONTENT_LIMIT] if body else None,
        char_count=len(body),
        chunk_count=len(old),
        chunk_snapshot=snapshot,
        reason=reason,
    )
    db.add(ver)
    await db.flush()
    logger.info("document_version_archived", document_id=doc.id, version=ver.version, reason=reason)
    return True


async def process_document(document_id: int) -> None:
    """完整处理一个文档。独立 session、幂等（按 status 判断）。"""
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, document_id)
        if not doc or doc.status in ("ready", "disabled"):
            return
        kb = await db.get(KnowledgeBase, doc.kb_id)
        tenant_id = doc.tenant_id
        stage = "parsing"
        try:
            # 归档旧版本（重灌/重新处理时保留上一版，供回滚）；仅当已有旧分块才自增版本
            if await _archive_version(db, doc, reason="reprocess"):
                doc.version = (doc.version or 1) + 1

            # 1. parse
            doc.status = "parsing"
            doc.progress = 10
            await db.commit()

            if doc.kind == "entry":
                # 图文条目：不解析文件，正文直接用录入的 content
                text = (doc.content or "").strip()
                if not text:
                    raise RuntimeError("条目内容为空")
                pages: list = []
                doc.char_count = len(text)
                doc.page_count = 1
                doc.progress = 35
                await db.commit()
            elif doc.source_type == "external_sync":
                # 外部导入同步：正文来自远端片段，已存在 doc.content，无需文件解析
                text = (doc.content or "").strip()
                if not text:
                    raise RuntimeError("同步文档内容为空")
                pages: list = []
                doc.char_count = len(text)
                doc.page_count = 1
                doc.progress = 35
                await db.commit()
            else:
                if not doc.file_key:
                    raise RuntimeError("文档缺少文件")
                storage = get_storage()
                path = storage.path(doc.file_key)
                parsed = parse_file(path, doc.file_ext)
                pages = parsed.pages
                doc.char_count = parsed.char_count
                doc.page_count = parsed.page_count
                doc.progress = 35
                await db.commit()
                text = parsed.text

            # 2. chunk
            stage = "chunking"
            doc.status = "chunking"
            strategy = (kb.chunk_strategy or {}) if kb else {}
            text_chunks = chunk_text(
                text,
                strategy=strategy.get("type", "parent_child"),
                child_size=strategy.get("child_size", 400),
                parent_size=strategy.get("parent_size", 1500),
                overlap=strategy.get("overlap", 50),
            )
            if not text_chunks:
                raise RuntimeError("文档无可提取文本")

            # 清理旧 chunk（重灌）
            from sqlalchemy import delete

            await db.execute(delete(Chunk).where(Chunk.doc_id == doc.id))

            # 文档级 ACL：统一由 doc_acl_service 决定 vis_scope 与 allow/deny
            from app.services.doc_acl_service import build_chunk_acl_fields

            acl_fields = await build_chunk_acl_fields(db, kb, doc)
            vis_scope = acl_fields["vis_scope"]
            new_chunks: list[Chunk] = []
            for tc in text_chunks:
                c = Chunk(
                    tenant_id=tenant_id,
                    kb_id=doc.kb_id,
                    doc_id=doc.id,
                    ordinal=tc.ordinal,
                    chunk_type=tc.chunk_type,
                    content=tc.content,
                    parent_content=tc.parent_content,
                    token_count=len(tc.content),
                    page=_guess_page(pages, tc.content),
                    vis_scope=vis_scope,
                    acl_allow=acl_fields.get("acl_allow"),
                    acl_deny=acl_fields.get("acl_deny"),
                    enabled=True,
                )
                db.add(c)
                new_chunks.append(c)
            await db.flush()
            # 建立父指针（ordinal → chunk id）
            ordinal_to_id = {c.ordinal: c.id for c in new_chunks}
            for tc, c in zip(text_chunks, new_chunks):
                if tc.parent_index is not None:
                    c.parent_id = ordinal_to_id.get(tc.parent_index)
            doc.chunk_count = len(new_chunks)
            doc.progress = 60
            await db.commit()

            # 3. embed（仅子块/扁平块）
            # 图文知识库（source_type=entry）不做向量嵌入：条目短、靠关键词（BM25）即可命中，无需 embedding 模型。
            stage = "embedding"
            doc.status = "embedding"
            embeddable = [c for c in new_chunks if c.chunk_type != "parent"]
            is_entry_kb = bool(kb and getattr(kb, "source_type", "local") == "entry")
            if embeddable and not is_entry_kb:
                from app.core.config import settings

                # KB 级向量模型：该库若指定了 embedding_model_id，用它而非租户默认，
                # 保证与检索时的 query 向量同源（否则跨模型算 cosine 无意义）。
                kb_model_id = getattr(kb, "embedding_model_id", None) if kb else None
                emb_driver, rm = await get_embedding(db, tenant_id=tenant_id, config_id=kb_model_id)
                texts = [c.content for c in embeddable]
                degraded_note = None
                try:
                    vecs = await emb_driver.embed(texts, model=rm.model_name)
                except Exception as e:  # noqa: BLE001
                    # 本地兜底降级：上游不可用时改用确定性哈希向量，保证文档能入库
                    if settings.embedding_fallback_local:
                        from app.providers.drivers.local_hash import LocalHashDriver

                        emb_driver = LocalHashDriver(dim=settings.embedding_dim)
                        vecs = await emb_driver.embed(texts)
                        degraded_note = (
                            f"（已降级为本地向量模型 local_hash：上游「{rm.model_name}」调用失败，"
                            f"语义检索质量下降，修复后在「模型管理」重配 embedding 并「重新处理」本文件可恢复）"
                        )
                        logger.warning("embed_degraded_to_local", document_id=doc.id, err=str(e)[:200])
                    else:
                        raise
                store = get_vector_store()
                await store.add_embeddings(db, [(c.id, v) for c, v in zip(embeddable, vecs)])
                if degraded_note:
                    doc.error_msg = degraded_note[:500]
            doc.progress = 95
            await db.commit()

            # 4. finalize
            doc.status = "ready"
            doc.progress = 100
            doc.error_detail = None
            import datetime as _dt

            doc.parsed_at = _dt.datetime.now(_dt.timezone.utc)
            await db.flush()
            if kb:
                # 据实重算，避免重灌/删除导致计数漂移
                from app.api.v1.document import _refresh_kb_counts

                await _refresh_kb_counts(db, kb.id)
            await db.commit()
            # 语料变更 → 失效 BM25 缓存
            from app.retrieval import bm25_cache

            bm25_cache.invalidate_tenant(doc.tenant_id)
            logger.info("ingest_done", document_id=doc.id, chunks=len(new_chunks))
            # 事件触发：文档入库完成
            try:
                from app.tasks.event_bus import publish

                await publish("document.ready", tenant_id=doc.tenant_id, payload={
                    "document_id": doc.id, "kb_id": doc.kb_id, "title": doc.title,
                    "chunk_count": len(new_chunks),
                })
            except Exception:  # noqa: BLE001
                logger.exception("event_publish_failed", document_id=doc.id)
        except Exception as e:  # noqa: BLE001
            from app.services.error_format import format_ingest_error, short_summary

            doc.status = "failed"
            err = format_ingest_error(e, stage=stage)
            doc.error_detail = err
            doc.error_msg = short_summary(err)[:500]
            await db.commit()
            logger.exception("ingest_failed", document_id=document_id)
            # 事件触发：文档入库失败
            try:
                from app.tasks.event_bus import publish

                await publish("document.failed", tenant_id=doc.tenant_id, payload={
                    "document_id": document_id, "kb_id": doc.kb_id, "title": doc.title,
                })
            except Exception:  # noqa: BLE001
                logger.exception("event_publish_failed", document_id=document_id)


def _guess_page(pages: list[dict], content: str) -> int | None:
    """依据内容在页文本中的出现位置粗定位页码。"""
    if not pages or len(pages) == 1:
        return pages[0]["page"] if pages else None
    snippet = content[:40]
    for p in pages:
        if snippet and snippet in (p.get("text") or ""):
            return p["page"]
    return pages[0]["page"] if pages else None


async def enqueue_document(document_id: int) -> None:
    await submit(f"ingest:{document_id}", lambda: process_document(document_id))
