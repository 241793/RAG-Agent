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
    """将多路排序结果融合。score = Σ weight_i * 1/(k + rank)。

    同时保留每路命中的**最高原始相似度**到 hit.raw_score：RRF 分是排名制、跨查询不可比，
    无法用于相关度阈值；而向量的余弦相似度 / BM25 分是绝对量，可用于阈值过滤。
    """
    scores: dict[str, float] = {}
    best: dict[str, VectorHit] = {}
    best_raw: dict[str, float] = {}
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
            # 记录该命中在各路中的最高原始相似度（用于阈值判断）
            raw = hit.raw_score if hit.raw_score is not None else hit.score
            if raw is not None:
                best_raw[key] = max(best_raw.get(key, float("-inf")), float(raw))

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if top_n:
        ordered = ordered[:top_n]

    result: list[VectorHit] = []
    for key, sc in ordered:
        hit = best[key]
        hit.raw_score = best_raw.get(key, sc)  # 原始相似度（可比，供 score_threshold）
        hit.score = sc                          # RRF 融合分（仅用于排序）
        hit.source = "fused"
        result.append(hit)
    return result
