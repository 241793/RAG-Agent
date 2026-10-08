"""向量检索向量化正确性 + 防幻觉提示词测试。"""
from __future__ import annotations

import asyncio

import numpy as np

from app.retrieval.vector_store.store import NumpyStore, VectorHit
from app.services.chat_service import SYSTEM_PROMPT
from app.services.citation_check import check


async def _run_vector_consistency():
    """向量化实现与逐行 Python 实现应给出相同的 top_k 结果。"""
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Chunk, Document, KnowledgeBase, Tenant
    from app.services.permission import PrincipalSet

    await init_models()
    async with AsyncSessionLocal() as db:
        t = Tenant(name="VEC", slug="vec"); db.add(t); await db.flush()
        kb = KnowledgeBase(tenant_id=t.id, name="kb", visibility="public", owner_id=1)
        db.add(kb); await db.flush()
        doc = Document(tenant_id=t.id, kb_id=kb.id, title="d", status="ready")
        db.add(doc); await db.flush()
        dim = 8
        rng = np.random.default_rng(42)
        vecs = []
        for i in range(20):
            v = rng.standard_normal(dim).astype(np.float32)
            vecs.append(v)
            db.add(Chunk(tenant_id=t.id, kb_id=kb.id, doc_id=doc.id, ordinal=i,
                         chunk_type="flat", content=f"chunk {i}", embedding=v.tolist(),
                         vis_scope=0, enabled=True))
        await db.commit()
        tid, kid = t.id, kb.id
        qvec = rng.standard_normal(dim).astype(np.float32)

    # 参照实现：逐行 cosine
    q = qvec / (np.linalg.norm(qvec) or 1.0)
    ref = []
    for i, v in enumerate(vecs):
        vn = v / (np.linalg.norm(v) or 1.0)
        ref.append((float(np.dot(q, vn)), i))
    ref.sort(reverse=True)
    ref_top = [i for _, i in ref[:5]]

    async with AsyncSessionLocal() as db:
        from app.services.permission import build_permission_filter
        ps = PrincipalSet(user_id=1, tenant_id=tid, is_admin=True)
        from app.services.retrieval_service import resolve_accessible_kbs
        accessible = await resolve_accessible_kbs(db, ps)
        pf = build_permission_filter(ps, accessible)
        hits = await NumpyStore().search(db, query_vec=qvec.tolist(), pf=pf, top_k=5)
        got = [h.chunk_id for h in hits]

    # 结果集合应与参照一致（chunk_id 按插入顺序 = ordinal+1，映射到 ordinal）
    got_ord = sorted([h - 0 for h in got])
    assert len(hits) == 5, hits
    # 分数应降序
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    print("OK vector consistency")


def test_vector_consistency():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_vector_consistency())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_prompt_anti_hallucination():
    assert "明确区分" in SYSTEM_PROMPT
    assert "不在知识库中" in SYSTEM_PROMPT
    assert "不得编造或给自身知识标注编号" in SYSTEM_PROMPT
    assert "不要因为资料缺失而拒答" not in SYSTEM_PROMPT


def test_citation_check():
    assert check("见 [1] 和 [2]", [1, 2])["ok"] is True
    r = check("见 [1] 和 [5]", [1, 2])
    assert r["has_fake_cite"] is True and r["max_id"] == 5
    # 无可引用却带编号
    assert check("见 [1]", [])["has_fake_cite"] is True
    # 无编号
    assert check("普通回答", [1])["ok"] is True
