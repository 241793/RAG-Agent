"""可观测性测试：结构化报错、embedding 降级、Provider 健康、日志端点。"""
from __future__ import annotations

import asyncio

import pytest

from app.core.errors import UpstreamError


# ---- 结构化报错 ----
def test_upstream_error_str_full():
    e = UpstreamError(
        "调用 /embeddings 失败", base_url="http://x/v1", model="m",
        status_code=404, raw="Not Found", purpose="embedding",
    )
    s = str(e)
    assert "http://x/v1" in s and "404" in s and "Not Found" in s
    assert e.upstream_status == 404


def test_format_ingest_error_404_suggestion():
    from app.services.error_format import format_ingest_error

    e = UpstreamError("失败", base_url="http://x/v1", model="m", status_code=404, purpose="embedding")
    d = format_ingest_error(e, stage="embedding")
    assert d["status_code"] == 404
    assert "embeddings" in d["suggestion"]
    assert d["stage"] == "embedding"
    assert d["base_url"] == "http://x/v1"


def test_format_ingest_error_401_429():
    from app.services.error_format import format_ingest_error

    for code, kw in ((401, "API Key"), (429, "限流")):
        d = format_ingest_error(UpstreamError("x", status_code=code), stage="embedding")
        assert kw in d["suggestion"]


def test_format_ingest_error_timeout():
    from app.services.error_format import format_ingest_error

    d = format_ingest_error(RuntimeError("request timed out"), stage="embedding")
    assert "超时" in d["suggestion"]


def test_short_summary():
    from app.services.error_format import short_summary

    s = short_summary({"summary": "embedding 阶段失败", "status_code": 404, "model": "m"})
    assert "404" in s and "m" in s


# ---- embedding 降级 ----
@pytest.mark.asyncio
async def test_embedding_driver_raises_upstream_error(monkeypatch):
    """上游 404 → openai_compat.embed 抛 UpstreamError（非裸 HTTPStatusError）。"""
    import httpx

    from app.providers.drivers import openai_compat as oc

    class FakeResp:
        status_code = 404
        text = "Not Found"
        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=httpx.Request("POST", "http://x"), response=self)

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return FakeResp()

    monkeypatch.setattr(oc.httpx, "AsyncClient", FakeClient)
    drv = oc.OpenAICompatibleDriver(base_url="http://x/v1", api_key="k")
    with pytest.raises(UpstreamError) as ei:
        await drv.embed(["hi"], model="m")
    assert ei.value.upstream_status == 404


def test_local_hash_fallback_produces_vectors():
    """降级驱动 local_hash 能出正确维度的向量（离线兜底可用）。"""
    from app.providers.drivers.local_hash import LocalHashDriver

    drv = LocalHashDriver(dim=64)

    async def run():
        return await drv.embed(["一段测试文本", "第二段"])

    vecs = asyncio.new_event_loop().run_until_complete(run())
    assert len(vecs) == 2 and len(vecs[0]) == 64


# ---- Provider 健康端点 ----
def test_provider_health_endpoint_registered():
    from app.api.v1.provider import router

    paths = {r.path for r in router.routes}
    assert "/providers/{provider_id}/health" in paths


@pytest.mark.asyncio
async def test_check_all_providers_writes_status(monkeypatch):
    """check_all_providers 对每个 active provider 回写 health_status/last_check_at。"""
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import ModelProvider, Tenant
    from app.tasks import health_tasks

    await init_models()
    async with AsyncSessionLocal() as db:
        t = Tenant(name="HT", slug="ht")
        db.add(t); await db.flush()
        p = ModelProvider(
            tenant_id=t.id, name="本地哈希", kind="local_hash",
            base_url="local", status="active", timeout=10,
        )
        db.add(p); await db.commit()
        pid = p.id

    n = await health_tasks.check_all_providers()
    assert n >= 1
    async with AsyncSessionLocal() as db:
        p = await db.get(ModelProvider, pid)
        assert p.health_status in ("ok", "fail")
        assert p.last_check_at and p.last_check_at > 0


# ---- 日志端点 ----
def test_system_logs_endpoint_registered():
    from app.api.v1.system import router

    paths = {r.path for r in router.routes}
    assert "/system/logs" in paths
    assert "/system/logs/download" in paths


def test_read_logs_returns_lines(tmp_path, monkeypatch):
    """写一个临时日志文件 → 端点读回最近行 + 关键字过滤。"""
    from app.core.config import settings
    from app.api.v1 import system as sysmod

    logf = tmp_path / "app.log"
    logf.write_text("\n".join(f'{{"level":"info","event":"line{i}"}}' for i in range(10)), encoding="utf-8")
    monkeypatch.setattr(settings, "log_file", str(logf))
    monkeypatch.setattr(settings, "log_backup_count", 0)

    class FakeUser:
        pass

    res = asyncio.new_event_loop().run_until_complete(sysmod.read_logs(lines=5, keyword=None, user=FakeUser()))
    assert res["total"] == 5
    res2 = asyncio.new_event_loop().run_until_complete(sysmod.read_logs(lines=100, keyword="line3", user=FakeUser()))
    assert res2["total"] == 1
