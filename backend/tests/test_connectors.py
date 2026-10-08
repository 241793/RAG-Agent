"""外部知识库连接器测试：加密、SSRF 守卫、generic_http 映射、RRF 兼容、retrieve 分流。"""
from __future__ import annotations

import asyncio

import pytest

from app.connectors.base import ConnectorDoc
from app.connectors.drivers.generic_http import GenericHttpConnector, map_records
from app.connectors.http_guard import assert_safe_url
from app.core.crypto import decrypt, encrypt, mask
from app.core.errors import ValidationError
from app.retrieval.fusion import rrf_fuse
from app.retrieval.vector_store.store import VectorHit


# ---- 加密 ----
def test_crypto_roundtrip():
    token = encrypt("sk-secret-123")
    assert token.startswith("enc:")
    assert decrypt(token) == "sk-secret-123"


def test_crypto_plaintext_passthrough():
    assert decrypt("plain-value") == "plain-value"
    assert decrypt(None) is None
    assert encrypt(None) is None


def test_crypto_mask():
    assert mask(encrypt("sk-abcdef123456")).startswith("sk")  # 首 2 位
    assert "••••" in mask(encrypt("sk-abcdef123456"))


# ---- SSRF 守卫 ----
def test_guard_blocks_loopback_and_private():
    for bad in ("http://127.0.0.1/x", "http://10.0.0.5/x", "http://169.254.1.1/x"):
        with pytest.raises(ValidationError):
            assert_safe_url(bad, allow_private=False)


def test_guard_rejects_non_http():
    with pytest.raises(ValidationError):
        assert_safe_url("ftp://example.com/x", allow_private=False)


def test_guard_allows_private_when_configured():
    # allow_private=True 时放行内网（企业内网部署）
    assert_safe_url("http://127.0.0.1/x", allow_private=True)


# ---- generic_http 映射 ----
def test_map_records_dotpath():
    payload = {
        "code": 0,
        "data": {
            "records": [
                {"content": "第一条", "title": "T1", "score": 0.9, "url": "http://a/1"},
                {"content": "第二条", "title": "T2", "score": 0.5},
            ]
        },
    }
    cfg = {
        "response_list_path": "data.records",
        "content_path": "content",
        "title_path": "title",
        "score_path": "score",
        "url_path": "url",
    }
    docs = map_records(payload, cfg, kb_id=7)
    assert len(docs) == 2
    assert docs[0].content == "第一条"
    assert docs[0].title == "T1"
    assert docs[0].score == 0.9
    assert docs[0].source_uri == "http://a/1"
    assert docs[0].ref == "kb7:0"


def test_map_records_root_array():
    docs = map_records([{"content": "x"}], {"content_path": "content"}, kb_id=1)
    assert len(docs) == 1 and docs[0].content == "x"


def test_map_records_bad_path_raises():
    with pytest.raises(ValidationError):
        map_records({"data": "not-a-list"}, {"response_list_path": "data"}, kb_id=1)


def test_generic_http_missing_base_url():
    with pytest.raises(ValidationError):
        GenericHttpConnector(kb_id=1, config={})


# ---- RRF 兼容外部键 ----
def _local(cid: int) -> VectorHit:
    return VectorHit(chunk_id=cid, doc_id=cid, kb_id=1, content=f"c{cid}", score=0.0)


def _ext(ref: str) -> VectorHit:
    return VectorHit(chunk_id=0, doc_id=0, kb_id=2, content=ref, score=0.0,
                     ext_ref=ref, ext_title="外部", source="external")


def test_rrf_external_and_local_no_collision():
    # 外部 chunk_id 也是 0，本地也是小 int：用 ext_ref 区分，不应互相覆盖
    fused = rrf_fuse([[_local(1), _local(2)], [_ext("kb2:e0"), _ext("kb2:e1")]], top_n=10)
    keys = {h.ext_ref or f"c{h.chunk_id}" for h in fused}
    assert keys == {"c1", "c2", "kb2:e0", "kb2:e1"}
    assert len(fused) == 4


def test_rrf_external_own_route_ranks_by_position():
    fused = rrf_fuse([[_ext("kb2:a"), _ext("kb2:b")]], top_n=2)
    assert fused[0].ext_ref == "kb2:a"


# ---- retrieve 分流：mock 连接器 ----
def _mk_split(local, external):
    async def _split(db, ids):
        return (local, external) if ids else ([], [])
    return _split


@pytest.mark.asyncio
async def test_retrieve_external_branch(monkeypatch):
    from app.services import retrieval_service as rs

    class FakeKB:
        id = 99
        name = "ext"
        source_type = "external"
        connector_kind = "generic_http"
        connector_config = {"base_url": "http://x"}

    monkeypatch.setattr(rs, "_split_local_external", _mk_split([], [FakeKB()]))

    async def fake_search(external_kbs, query, *, top_k, warnings):
        return [VectorHit(chunk_id=0, doc_id=0, kb_id=99, content="外部命中内容",
                          score=0.02, ext_ref="kb99:e0", ext_title="ExtDoc", source="external")]

    monkeypatch.setattr(rs, "_search_external", fake_search)

    class FakePS:
        tenant_id = 1
        user_id = 1
        is_admin = True
        principals = [0]

    async def fake_build_filter(db, ps, kb_ids=None, force_kb_ids=None):
        from app.services.permission import PermissionFilter
        return PermissionFilter(tenant_id=1, accessible_kb_ids=[99], principals=[0])

    monkeypatch.setattr(rs, "build_filter", fake_build_filter)

    # 让本地向量/BM25 都返回空、不抛错
    class EmptyStore:
        async def search(self, db, **kw):
            return []

    monkeypatch.setattr(rs, "get_vector_store", lambda: EmptyStore())

    async def fake_embed(db, *, tenant_id, query):
        return [0.0]

    monkeypatch.setattr(rs, "embed_query", fake_embed)

    resp = await rs.retrieve(None, ps=FakePS(), query="test", kb_ids=[99], top_k=3, use_hybrid=False)
    assert len(resp.chunks) == 1
    assert resp.chunks[0].external is True
    assert resp.chunks[0].doc_title == "ExtDoc"


@pytest.mark.asyncio
async def test_retrieve_external_failure_degrades(monkeypatch):
    from app.services import retrieval_service as rs

    class FakeKB:
        id = 88
        name = "ext-err"
        source_type = "external"
        connector_kind = "generic_http"
        connector_config = {"base_url": "http://x"}

    monkeypatch.setattr(rs, "_split_local_external", _mk_split([], [FakeKB()]))

    async def boom(external_kbs, query, *, top_k, warnings):
        warnings.append("external_unavailable:88")
        return []

    monkeypatch.setattr(rs, "_search_external", boom)

    class FakePS:
        tenant_id = 1
        user_id = 1
        is_admin = True
        principals = [0]

    async def fake_build_filter(db, ps, kb_ids=None, force_kb_ids=None):
        from app.services.permission import PermissionFilter
        return PermissionFilter(tenant_id=1, accessible_kb_ids=[88], principals=[0])

    monkeypatch.setattr(rs, "build_filter", fake_build_filter)

    class EmptyStore:
        async def search(self, db, **kw):
            return []

    monkeypatch.setattr(rs, "get_vector_store", lambda: EmptyStore())

    async def fake_embed(db, *, tenant_id, query):
        return [0.0]

    monkeypatch.setattr(rs, "embed_query", fake_embed)

    resp = await rs.retrieve(None, ps=FakePS(), query="test", kb_ids=[88], top_k=3, use_hybrid=False)
    assert resp.degraded is True
    assert any("external_unavailable" in w for w in resp.warnings)


def test_connector_endpoints_registered():
    from app.api.v1.kb import router

    paths = {r.path for r in router.routes}
    assert "/kbs/connector/test" in paths
    assert "/kbs/{kb_id}/connector" in paths
    assert "/kbs/{kb_id}/connector/test" in paths
