"""RAG 检索修复测试：RRF 保留原始分（不再 top-1 恒为 1.0）。"""
from __future__ import annotations

from app.retrieval.fusion import rrf_fuse
from app.retrieval.vector_store.store import VectorHit


def _hit(cid: int, score: float = 0.0) -> VectorHit:
    return VectorHit(chunk_id=cid, doc_id=cid, kb_id=1, content=f"c{cid}", score=score)


def test_rrf_keeps_raw_score_not_normalized():
    # score == raw_score；单路 rank1 = 1/(60+1) ≈ 0.0164，不再恒为 1.0
    fused = rrf_fuse([[_hit(1), _hit(2), _hit(3)]], top_n=3)
    assert fused[0].chunk_id == 1
    assert abs(fused[0].score - 1 / 61) < 1e-9
    assert fused[0].raw_score == fused[0].score
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_multi_route_consensus_higher():
    # 两路都排第一的块，RRF 原始分 = 2/(60+1)，高于只在一路排第一的
    fused = rrf_fuse([[_hit(1), _hit(2)], [_hit(1), _hit(3)]], top_n=3)
    assert fused[0].chunk_id == 1
    assert abs(fused[0].score - 2 / 61) < 1e-9


def test_rrf_threshold_is_monotonic_comparable():
    # 高阈值下（如 0.03）单路结果（≈0.016）被排除——阈值语义清晰、跨查询可比
    fused = rrf_fuse([[_hit(1), _hit(2)]], top_n=2)
    assert all(h.score < 0.03 for h in fused)
    assert [h for h in fused if h.score >= 0.03] == []
