"""BM25 索引的进程内缓存：避免每次检索全库重新分词/重建 idf。

key = (tenant_id, 代次, kb 集合或 None)。文档增删时 bump 代次使缓存失效。
用简单的容量上限淘汰，防多租户累积。
"""
from __future__ import annotations

from collections import OrderedDict

from app.retrieval.bm25 import BM25, build_index, tokenize  # noqa: F401

_MAX_ENTRIES = 8
_CACHE: "OrderedDict[tuple, tuple[BM25, list]]" = OrderedDict()
_GEN: dict[int, int] = {}


def _gen(tenant_id: int) -> int:
    return _GEN.get(tenant_id, 0)


def invalidate_tenant(tenant_id: int) -> None:
    """文档增删后调用：使该租户所有 BM25 缓存失效。"""
    _GEN[tenant_id] = _gen(tenant_id) + 1


def make_key(tenant_id: int, kb_ids: list[int] | None, bypass_kb: bool) -> tuple:
    kb_key = None if bypass_kb else frozenset(kb_ids or [])
    return (tenant_id, _gen(tenant_id), kb_key, bypass_kb)


def get(tenant_id: int, kb_ids: list[int] | None, bypass_kb: bool):
    key = make_key(tenant_id, kb_ids, bypass_kb)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def put(tenant_id: int, kb_ids: list[int] | None, bypass_kb: bool, rows: list) -> tuple[BM25, list]:
    key = make_key(tenant_id, kb_ids, bypass_kb)
    index = build_index(rows)
    _CACHE[key] = (index, rows)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _MAX_ENTRIES:
        _CACHE.popitem(last=False)
    return index, rows


def clear() -> None:
    _CACHE.clear()
