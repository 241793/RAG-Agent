"""关键词检索（BM25 的轻量近似）。

- PostgreSQL: 可用 tsvector/zhparser（预留），此处统一走应用层打分以保持跨库一致。
- SQLite/MySQL: 应用层对候选集做 BM25 打分。
为控制内存，先在 SQL 层用 LIKE 粗召回（可选），再 BM25 精排。
"""
from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk
from app.retrieval.vector_store.store import VectorHit, _apply_permission, _dialect_of
from app.services.permission import PermissionFilter, chunk_visible_py

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """中文按双字（bigram）+ 单字，英文数字按词。零依赖，比单字召回更准。"""
    out: list[str] = []
    for seg in _TOKEN_RE.findall(text):
        if seg.isascii():
            out.append(seg.lower())
        else:
            out.append(seg)  # 整段中文也保留，命中长词
            for ch in seg:
                out.append(ch)  # 单字（短词/召回兜底）
            for i in range(len(seg) - 1):
                out.append(seg[i:i + 2])  # 双字
    return out


class BM25:
    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75,
                 counters: list[Counter] | None = None) -> None:
        self.k1 = k1
        self.b = b
        self.docs = corpus_tokens
        self.n = len(corpus_tokens)
        self.avgdl = (sum(len(d) for d in corpus_tokens) / self.n) if self.n else 0.0
        self.df: Counter = Counter()
        for d in corpus_tokens:
            for term in set(d):
                self.df[term] += 1
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5))
            for term, freq in self.df.items()
        }
        # 预存每行词频 Counter（避免每次打分重建）
        self.counters = counters if counters is not None else [Counter(d) for d in corpus_tokens]

    def score(self, query_tokens: list[str], idx: int) -> float:
        tf = self.counters[idx]
        dl = len(self.docs[idx]) or 1
        s = 0.0
        for term in query_tokens:
            freq = tf.get(term)
            if not freq:
                continue
            idf = self.idf.get(term, 0.0)
            s += idf * (freq * (self.k1 + 1)) / (freq + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
        return s


def build_index(rows: list[tuple]) -> BM25:
    """由行数据（含 content 在 r[3]）构建可复用的 BM25 索引。"""
    corpus = [tokenize(r[3] or "") for r in rows]
    return BM25(corpus)


async def keyword_search(
    db: AsyncSession, *, query: str, pf: PermissionFilter, top_k: int,
    index: BM25 | None = None, rows: list[tuple] | None = None,
    on_build: "callable | None" = None,
) -> list[VectorHit]:
    """关键词检索。传入预构建的 index+rows（缓存）可避免每次全库重分词。

    on_build(index, rows)：本次**新建**了索引时回调，供调用方写入缓存。
    """
    if index is None or rows is None:
        dialect = _dialect_of(db)
        stmt = select(
            Chunk.id, Chunk.doc_id, Chunk.kb_id, Chunk.content, Chunk.page,
            Chunk.parent_content, Chunk.section,
            Chunk.vis_scope, Chunk.acl_allow, Chunk.acl_deny,
        )
        stmt = _apply_permission(stmt, pf, dialect)
        rows = (await db.execute(stmt)).all()
        if not rows:
            return []
        # 纵深防御：Python 再校验一次可见性
        pset = set(pf.principals)
        rows = [r for r in rows if chunk_visible_py(pset, r[7], r[8], r[9])]
        index = build_index(rows)
        if on_build is not None:
            try:
                on_build(index, rows)
            except Exception:  # noqa: BLE001
                pass

    if not rows:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, tuple]] = []
    for i, row in enumerate(rows):
        sc = index.score(query_tokens, i)
        if sc > 0:
            scored.append((sc, row))
    scored.sort(key=lambda x: x[0], reverse=True)

    # 归一化到 0-1（BM25 原始分保留在 raw_score）
    max_s = scored[0][0] if scored else 1.0
    hits: list[VectorHit] = []
    for sc, row in scored[:top_k]:
        hits.append(
            VectorHit(
                chunk_id=row[0], doc_id=row[1], kb_id=row[2], content=row[3],
                score=sc / max_s if max_s else 0.0, raw_score=sc, page=row[4],
                parent_content=row[5], section=row[6], source="bm25",
            )
        )
    return hits
