"""RRF (Reciprocal Rank Fusion) 融合多路检索结果。"""
from __future__ import annotations

from app.retrieval.vector_store.store import VectorHit


def _key(hit: VectorHit) -> str:
    """去重键：外部命中用 ext_ref，本地命中用 "c{chunk_id}"（统一字符串，防撞车）。"""
    return hit.ext_ref or f"c{hit.chunk_id}"


def rrf_fuse(
    rankings: list[list[VectorHit]],
    k: int = 60,
    top_n: int | None = None,
    weights: list[float] | None = None,
) -> list[VectorHit]:
    """将多路排序结果融合。score = Σ weight_i * 1/(k + rank)。"""
    scores: dict[str, float] = {}
    best: dict[str, VectorHit] = {}
    for i, ranking in enumerate(rankings):
        w = 1.0
        if weights and i < len(weights):
            w = float(weights[i])
        for rank, hit in enumerate(ranking, start=1):
            key = _key(hit)
            scores[key] = scores.get(key, 0.0) + w * (1.0 / (k + rank))
            # 保留内容更完整的记录（父块内容优先）
            if key not in best or (hit.parent_content and not best[key].parent_content):
                best[key] = hit

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if top_n:
        ordered = ordered[:top_n]

    # 保留原始 RRF 分：k 与 rank 固定，故跨查询可比、单调。
    # 注意：RRF 是排名制，无法表达绝对相关度——判"无命中"应靠余弦前置门
    # （settings.retrieval_vec_min），而非此分数。score = raw_score（不归一化，
    # 避免 sc/max 使 top-1 恒为 1.0 而失去阈值意义）。
    result: list[VectorHit] = []
    for key, sc in ordered:
        hit = best[key]
        hit.raw_score = sc
        hit.score = sc
        hit.source = "fused"
        result.append(hit)
    return result
