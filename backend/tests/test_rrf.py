"""RAG 检索融合测试：RRF 排序分与原始相似度分离。

- score      = RRF 融合分（排名制，仅用于排序）
- raw_score  = 该命中在各路中的最高原始相似度（余弦/BM25，跨查询可比，用于阈值过滤）
"""
from __future__ import annotations

from app.retrieval.fusion import rrf_fuse
from app.retrieval.vector_store.store import VectorHit


def _hit(cid: int, score: float = 0.0) -> VectorHit:
    return VectorHit(chunk_id=cid, doc_id=cid, kb_id=1, content=f"c{cid}", score=score)


def test_rrf_score_is_rank_based():
    # score 为 RRF 分：单路 rank1 = 1/(60+1) ≈ 0.0164（不归一化）
    fused = rrf_fuse([[_hit(1), _hit(2), _hit(3)]], top_n=3)
    assert fused[0].chunk_id == 1
    assert abs(fused[0].score - 1 / 61) < 1e-9
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_multi_route_consensus_higher():
    # 两路都排第一的块，RRF 分 = 2/(60+1)，高于只在一路排第一的
    fused = rrf_fuse([[_hit(1), _hit(2)], [_hit(1), _hit(3)]], top_n=3)
    assert fused[0].chunk_id == 1
    assert abs(fused[0].score - 2 / 61) < 1e-9


def test_raw_score_keeps_original_similarity():
    # 原始相似度（可比）被保留在 raw_score，供 score_threshold 判断——而非 RRF 分
    hits = [_hit(1, score=0.91), _hit(2, score=0.42)]
    fused = rrf_fuse([hits], top_n=2)
    by_id = {h.chunk_id: h for h in fused}
    assert abs(by_id[1].raw_score - 0.91) < 1e-9
    assert abs(by_id[2].raw_score - 0.42) < 1e-9
    # 排序仍按 RRF 分
    assert fused[0].chunk_id == 1


def test_raw_score_takes_max_across_routes():
    # 同一块出现在多路时，raw_score 取最高原始相似度
    vec = [_hit(1, score=0.5)]
    bm25 = [_hit(1, score=0.88)]
    fused = rrf_fuse([vec, bm25], top_n=1)
    assert abs(fused[0].raw_score - 0.88) < 1e-9
