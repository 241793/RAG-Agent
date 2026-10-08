"""MMR（最大边际相关）去冗余：在相关性排序基础上，惩罚与已选结果高度相似的候选项，
提升结果多样性，避免同一内容的多份文档挤占 top_k。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.vector_store.store import VectorHit


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（无 numpy 时纯 Python 兜底）。"""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = sum(x * x for x in a[:n]) ** 0.5
    nb = sum(x * x for x in b[:n]) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def mmr_select(
    db: AsyncSession, hits: list[VectorHit], *, top_k: int, lambda_: float = 0.7,
) -> list[VectorHit]:
    """对融合结果做 MMR 重排，返回 top_k。无向量的命中视为互不相似、直接保留。

    相关性用 hit.score（RRF/相似度，越大越相关），并按最大值归一到 [0,1] 以与相似度同尺度。
    """
    if len(hits) <= top_k or top_k <= 0:
        return hits

    from app.models import Chunk

    local_ids = [h.chunk_id for h in hits if not h.ext_ref and h.chunk_id]
    vec_map: dict[int, list[float]] = {}
    if local_ids:
        rows = (await db.execute(
            select(Chunk.id, Chunk.embedding).where(Chunk.id.in_(local_ids))
        )).all()
        for cid, emb in rows:
            if emb:
                vec_map[cid] = list(emb)

    # 相关性归一到 [0,1]
    max_sc = max((h.score for h in hits), default=1.0) or 1.0
    rel = {i: (hits[i].score / max_sc) for i in range(len(hits))}

    def sim(i: int, j: int) -> float:
        vi = vec_map.get(hits[i].chunk_id)
        vj = vec_map.get(hits[j].chunk_id)
        if not vi or not vj:
            return 0.0
        return _cosine(vi, vj)

    selected: list[int] = []
    remaining = list(range(len(hits)))
    while remaining and len(selected) < top_k:
        best_i, best_val = remaining[0], float("-inf")
        for i in remaining:
            if not selected:
                val = rel[i]
            else:
                max_sim = max(sim(i, j) for j in selected)
                val = lambda_ * rel[i] - (1 - lambda_) * max_sim
            if val > best_val:
                best_val, best_i = val, i
        selected.append(best_i)
        remaining.remove(best_i)

    return [hits[i] for i in selected]
