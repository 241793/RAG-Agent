"""检索编排服务：权限解析 → 向量+关键词召回 → RRF 融合 → 父子补全。"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KBMember, KnowledgeBase
from app.retrieval.bm25 import keyword_search
from app.retrieval.fusion import rrf_fuse
from app.retrieval.vector_store.store import VectorHit, get_vector_store
from app.providers.registry import get_embedding
from app.schemas.chat import Citation, RetrievalResponse, RetrievedChunk
from app.services.permission import (
    PermissionFilter,
    PrincipalSet,
    build_permission_filter,
    filter_accessible_kbs,
)


async def resolve_accessible_kbs(db: AsyncSession, ps: PrincipalSet) -> list[int]:
    """查询该主体可访问的知识库 id 列表（权限感知检索的第一道过滤）。"""
    rows = (
        await db.execute(
            select(KnowledgeBase.id, KnowledgeBase.visibility).where(
                KnowledgeBase.tenant_id == ps.tenant_id,
                KnowledgeBase.status == "active",
            )
        )
    ).all()
    # 取各 KB 的成员 principal
    kb_ids = [r[0] for r in rows]
    member_map: dict[int, list[int]] = {}
    if kb_ids:
        members = (
            await db.execute(
                select(KBMember.kb_id, KBMember.principal_id).where(KBMember.kb_id.in_(kb_ids))
            )
        ).all()
        for kb_id, principal_id in members:
            member_map.setdefault(kb_id, []).append(principal_id)

    kb_rows = [
        {"kb_id": r[0], "visibility": r[1], "principals": member_map.get(r[0], [])}
        for r in rows
    ]
    return filter_accessible_kbs(ps, kb_rows)


async def build_filter(
    db: AsyncSession,
    ps: PrincipalSet,
    kb_ids: list[int] | None = None,
    force_kb_ids: list[int] | None = None,
) -> PermissionFilter:
    accessible = await resolve_accessible_kbs(db, ps)
    # API Key 强制限制：先与可访问集合取交集
    if force_kb_ids is not None:
        allowed = set(force_kb_ids)
        accessible = [k for k in accessible if k in allowed]
    if kb_ids:
        # 请求显式指定了知识库范围：无论谁，都必须限定在该范围内
        requested = set(kb_ids)
        if ps.is_admin and force_kb_ids is None:
            scoped = list(requested)
        else:
            # 非管理员（或受限 key）：取「可访问」与「请求范围」的交集
            scoped = [k for k in accessible if k in requested]
        return PermissionFilter(
            tenant_id=ps.tenant_id,
            accessible_kb_ids=scoped,
            principals=ps.principals,
            bypass_kb=False,
        )
    return build_permission_filter(ps, accessible, force_kb_ids=force_kb_ids)


async def embed_query(db: AsyncSession, *, tenant_id: int, query: str) -> list[float]:
    emb_driver, rm = await get_embedding(db, tenant_id=tenant_id)
    vecs = await emb_driver.embed([query], model=rm.model_name)
    return vecs[0]


# 追问/指代信号：短句 + 指代词 → 需要结合上下文改写再检索
_REFER_WORDS = ("它", "他", "她", "这个", "那个", "这", "那", "这些", "那些", "该", "此", "上述", "前面", "刚才", "呢", "还有")


def _needs_condense(query: str) -> bool:
    """启发式判断 query 是否依赖上下文（短句或含指代词）。"""
    q = (query or "").strip()
    if not q or len(q) > 40:
        return False
    if len(q) <= 12:
        return True
    return any(w in q for w in _REFER_WORDS)


async def condense_query(db: AsyncSession, *, tenant_id: int, query: str, history: list) -> str:
    """多轮追问改写：把「最近上下文 + 当前 query」压成独立完整问题。失败回退原文。"""
    from app.core.config import settings

    if not getattr(settings, "query_rewrite_enabled", True):
        return query
    if not history or not _needs_condense(query):
        return query
    # 取最近 3 轮 user 消息作上下文
    recent = [m.content for m in history[-6:] if getattr(m, "role", "") == "user" and m.content][-3:]
    if not recent:
        return query
    try:
        from app.providers.base import ChatMessage
        from app.providers.registry import get_llm

        llm, rm = await get_llm(db, tenant_id=tenant_id)
        sys = ("你是检索查询改写器。用户的问题可能是省略主语的追问（用「它/这个/上述」等指代）。"
               "请结合历史对话，把它改写成**一个独立、完整、可检索**的问题。"
               "只输出改写后的问题本身，不要解释、不要引号。若问题已完整，原样输出。")
        usr = "【历史对话】\n" + "\n".join(f"- {c}" for c in recent) + f"\n\n【当前问题】\n{query}\n\n【改写】"
        res = await llm.chat(
            [ChatMessage(role="system", content=sys), ChatMessage(role="user", content=usr)],
            model=rm.model_name, stream=False, temperature=0.0,
        )
        out = (getattr(res, "content", "") or "").strip().strip('"').strip("'")
        # 合理性校验：非空、不太长、不是空话
        if 0 < len(out) <= 200:
            return out
    except Exception:  # noqa: BLE001
        pass
    return query


async def _split_local_external(
    db: AsyncSession, kb_ids: list[int]
) -> tuple[list[int], list]:
    """把 KB 列表拆成 (本地 kb_ids, 外部 KB 行列表)。"""
    if not kb_ids:
        return [], []
    rows = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
        )
    ).scalars().all()
    local_ids: list[int] = []
    external: list = []
    for kb in rows:
        if getattr(kb, "source_type", "local") == "external":
            external.append(kb)
        else:
            local_ids.append(kb.id)
    return local_ids, external


async def _has_vector_kb(db: AsyncSession, kb_ids: list[int]) -> bool:
    """目标库里是否有需要向量召回的库（非图文库）。空列表也返回 True（走默认路径）。"""
    if not kb_ids:
        return True
    from app.models import KnowledgeBase

    rows = (await db.execute(
        select(KnowledgeBase.source_type).where(KnowledgeBase.id.in_(kb_ids))
    )).scalars().all()
    return any((st or "local") != "entry" for st in rows)


async def _search_external(
    external_kbs: list, query: str, *, top_k: int, warnings: list[str]
) -> list:
    """并发检索所有外部知识库，归一化为 VectorHit。单源失败不阻断。"""
    import asyncio

    from app.connectors.registry import from_kb
    from app.core.config import settings
    from app.core.logging import get_logger

    log = get_logger("retrieval")
    cap = settings.connector_max_top_k

    async def _one(kb):
        try:
            conn = from_kb(kb)
            if conn is None:
                return []
            docs = await conn.search(query, top_k=min(top_k, cap))
            hits: list[VectorHit] = []
            for rank, d in enumerate(docs, start=1):
                hits.append(
                    VectorHit(
                        chunk_id=0, doc_id=0, kb_id=kb.id, content=d.content,
                        score=1.0 / (60 + rank),  # 占位；真实分由 rrf 决定
                        page=d.page, ext_ref=d.ref or f"kb{kb.id}:{rank}",
                        ext_title=d.title, source_uri=d.source_uri,
                        source="external",
                    )
                )
            return hits
        except Exception as e:  # noqa: BLE001
            log.warning("external_search_failed", kb_id=kb.id, err=str(e)[:200])
            warnings.append(f"external_unavailable:{kb.id}")
            return []

    if not external_kbs:
        return []
    results = await asyncio.gather(*[_one(kb) for kb in external_kbs])
    out: list[VectorHit] = []
    for r in results:
        out.extend(r)
    return out


async def retrieve(
    db: AsyncSession,
    *,
    ps: PrincipalSet,
    query: str,
    kb_ids: list[int] | None = None,
    top_k: int = 5,
    use_hybrid: bool = True,
    candidate_k: int = 20,
    score_threshold: float = 0.0,
    use_rerank: bool | None = None,
) -> RetrievalResponse:
    from app.core.config import settings

    t0 = time.time()
    pf = await build_filter(db, ps, kb_ids)
    warnings: list[str] = []
    degraded = False

    # 拆分本地 / 外部知识库来源
    local_ids, external_kbs = await _split_local_external(db, pf.accessible_kb_ids)
    if external_kbs:
        pf.accessible_kb_ids = local_ids

    store = get_vector_store()
    rankings: list[tuple[str, list[VectorHit]]] = []  # (来源标签, 结果)

    # 外部知识库联邦检索（并发，单源失败不阻断）
    if external_kbs:
        ext_hits = await _search_external(external_kbs, query, top_k=candidate_k, warnings=warnings)
        if ext_hits:
            rankings.append(("external", ext_hits))
        if warnings:
            degraded = True

    # 向量召回（仅本地）。若目标库全是图文库（source_type=entry，不做向量嵌入），跳过向量召回、直接走 BM25。
    has_vector_kb = await _has_vector_kb(db, local_ids)
    if has_vector_kb:
        try:
            qvec = await embed_query(db, tenant_id=ps.tenant_id, query=query)
            vec_hits = await store.search(db, query_vec=qvec, pf=pf, top_k=candidate_k,
                                          max_scan=settings.vector_max_scan or None)
            if settings.retrieval_vec_min > 0:
                vec_hits = [h for h in vec_hits if h.score >= settings.retrieval_vec_min]
            rankings.append(("vector", vec_hits))
        except Exception:  # noqa: BLE001
            from app.core.logging import get_logger

            get_logger("retrieval").exception("vector_search_failed")
            degraded = True
            warnings.append("vector_unavailable")

    # 关键词召回（BM25，带索引缓存）
    if use_hybrid:
        from app.retrieval import bm25_cache

        cached = bm25_cache.get(ps.tenant_id, pf.accessible_kb_ids, pf.bypass_kb)
        if cached:
            index, rows = cached
            kw_hits = await keyword_search(db, query=query, pf=pf, top_k=candidate_k, index=index, rows=rows)
        else:
            kw_hits = await keyword_search(db, query=query, pf=pf, top_k=candidate_k)
        if settings.retrieval_bm25_min > 0:
            kw_hits = [h for h in kw_hits if h.score >= settings.retrieval_bm25_min]
        rankings.append(("bm25", kw_hits))

    if len(rankings) > 1:
        wmap = {"vector": settings.rrf_weight_vector, "bm25": settings.rrf_weight_bm25,
                "external": settings.rrf_weight_external}
        fused = rrf_fuse([r for _s, r in rankings], k=settings.rrf_k,
                         top_n=max(candidate_k, top_k),
                         weights=[wmap.get(s, 1.0) for s, _r in rankings])
    elif rankings:
        fused = rankings[0][1][:max(candidate_k, top_k)]
    else:
        fused = []

    # MMR 去冗余（可选）：在重排前对候选做多样性重排，避免近重复内容挤占名额
    if settings.mmr_enabled and len(fused) > top_k:
        from app.retrieval.mmr import mmr_select

        pool_n = settings.rerank_pool if settings.rerank_enabled else top_k
        fused = await mmr_select(db, fused, top_k=max(top_k, pool_n), lambda_=settings.mmr_lambda)

    # 重排（可选）
    rerank_on = settings.rerank_enabled if use_rerank is None else use_rerank
    if rerank_on and fused:
        fused, rr_degraded = await _rerank(
            db, tenant_id=ps.tenant_id, query=query, fused=fused,
            pool=settings.rerank_pool, top_k=top_k,
        )
        if rr_degraded:
            warnings.append("rerank_unavailable")

    fused = fused[:top_k]

    # 相关度阈值过滤（阈值为 0 时不过滤）
    if score_threshold > 0:
        fused = [h for h in fused if h.score >= score_threshold]

    chunks = await _to_chunks(db, fused)
    # 未命中日志（异步、不阻塞）——供知识库运营发现缺口
    if not chunks and (query or "").strip():
        try:
            import asyncio

            asyncio.create_task(_log_miss(ps.tenant_id, query, pf.accessible_kb_ids, ps.user_id))
        except Exception:  # noqa: BLE001
            pass
    return RetrievalResponse(
        query=query, chunks=chunks, timing_ms=int((time.time() - t0) * 1000),
        trusted=len(chunks) > 0, degraded=degraded, warnings=warnings,
    )


async def _log_miss(tenant_id: int, query: str, kb_ids: list[int], user_id: int | None) -> None:
    """独立 session 记录未命中（失败静默）。"""
    try:
        from app.core.db import AsyncSessionLocal
        from app.models import RetrievalMiss

        async with AsyncSessionLocal() as db:
            db.add(RetrievalMiss(
                tenant_id=tenant_id, query=query[:500],
                kb_ids=",".join(str(k) for k in (kb_ids or [])[:20]), user_id=user_id,
            ))
            await db.commit()
    except Exception:  # noqa: BLE001
        pass


async def _rerank(
    db: AsyncSession, *, tenant_id: int, query: str, fused: list[VectorHit],
    pool: int, top_k: int,
) -> tuple[list[VectorHit], bool]:
    """融合后重排。无真模型/失败时返回原序；失败返回 (原序, True)。"""
    from app.core.config import settings
    from app.core.logging import get_logger

    log = get_logger("retrieval")
    if len(fused) <= 1:
        return fused, False
    try:
        from app.providers.registry import get_rerank

        resolved = await get_rerank(db, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001
        resolved = None
    if not resolved:
        return fused, False
    driver, rm = resolved
    kind = getattr(rm, "provider_kind", None)
    if kind == "local_hash" and not settings.rerank_allow_fake:
        return fused, False

    cand = fused[:pool]
    docs = [h.parent_content or h.content for h in cand]
    try:
        if _accepts_model(driver.rerank):
            pairs = await driver.rerank(query, docs, top_n=top_k, model=rm.model_name)
        else:
            pairs = await driver.rerank(query, docs, top_n=top_k)
    except Exception:  # noqa: BLE001
        log.exception("rerank_failed")
        return fused, True

    out: list[VectorHit] = []
    seen: set[int] = set()
    rmax = max((s for _, s in pairs), default=1.0) or 1.0
    for idx, sc in pairs:
        if 0 <= idx < len(cand):
            h = cand[idx]
            h.rerank_score = float(sc)
            h.score = float(sc) / rmax
            h.source = "rerank"
            out.append(h)
            seen.add(idx)
    for i, h in enumerate(cand):
        if i not in seen:
            out.append(h)
    out.extend(fused[pool:])
    return out, False


def _accepts_model(fn) -> bool:
    import inspect

    try:
        return "model" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


async def _to_chunks(db: AsyncSession, hits: list[VectorHit]) -> list[RetrievedChunk]:
    if not hits:
        return []
    from app.models import Document

    # 本地命中才需要查文档标题；外部命中自带 ext_title
    doc_ids = list({h.doc_id for h in hits if not h.ext_ref and h.doc_id})
    title_map: dict[int, str] = {}
    att_map: dict[int, list] = {}
    if doc_ids:
        docs = (
            await db.execute(
                select(Document.id, Document.title, Document.attachments).where(Document.id.in_(doc_ids))
            )
        ).all()
        title_map = {d[0]: d[1] for d in docs}
        # 图文条目：把配套附件带出来（命中后随回答发给提问者）
        att_map = {d[0]: d[2] for d in docs if d[2]}

    out: list[RetrievedChunk] = []
    for h in hits:
        # 父子补全：命中子块时用父块内容增强上下文
        content = h.parent_content or h.content
        if h.ext_ref:
            out.append(
                RetrievedChunk(
                    chunk_id=0, doc_id=0, kb_id=h.kb_id,
                    content=content, score=round(h.score, 4), page=h.page,
                    doc_title=h.ext_title or f"外部知识库#{h.kb_id}",
                    source="external", external=True, source_uri=h.source_uri,
                )
            )
        else:
            out.append(
                RetrievedChunk(
                    chunk_id=h.chunk_id, doc_id=h.doc_id, kb_id=h.kb_id,
                    content=content, score=round(h.score, 4), page=h.page,
                    doc_title=title_map.get(h.doc_id), source="fused",
                    attachments=att_map.get(h.doc_id),
                )
            )
    return out


def to_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            doc_title=c.doc_title,
            page=c.page,
            score=c.score,
            snippet=(c.content or "")[:120],
            source_uri=c.source_uri,
            attachments=c.attachments,
        )
        for c in chunks
    ]
