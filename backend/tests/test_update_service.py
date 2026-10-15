"""更新检查服务测试：版本比较、部署形态判定、优雅降级、缓存。

httpx 出站被 mock（不经网络），验证逻辑与错误路径。
"""
from __future__ import annotations

import asyncio

from app.services import update_service as U


# ---------- 版本比较 ----------

def test_parse_version_forms():
    assert U._parse_version("1.0.0") == (1, 0, 0)
    assert U._parse_version("v1.2.3") == (1, 2, 3)
    assert U._parse_version("V2.0") == (2, 0)
    assert U._parse_version("1.2.3-rc1") == (1, 2, 3)
    assert U._parse_version("1.2.3+build.5") == (1, 2, 3)
    assert U._parse_version("") is None
    assert U._parse_version("abc") is None
    assert U._parse_version("1.x.0") is None


def test_is_newer_semver():
    assert U.is_newer("1.0.1", "1.0.0")
    assert U.is_newer("1.1.0", "1.0.9")
    # 数值比较而非字符串：1.0.10 > 1.0.9
    assert U.is_newer("1.0.10", "1.0.9")
    assert U.is_newer("2.0.0", "1.99.99")
    assert not U.is_newer("1.0.0", "1.0.0")
    assert not U.is_newer("1.0.0", "1.0.1")
    # 长度补齐：1.0 == 1.0.0
    assert not U.is_newer("1.0", "1.0.0")
    assert not U.is_newer("1.0.0", "1.0")
    # v 前缀与预发布后缀
    assert U.is_newer("v1.0.1", "1.0.0")
    assert U.is_newer("1.0.1-rc1", "1.0.0")


def test_is_newer_unparseable_is_conservative():
    """不可解析时不得误报有更新。"""
    assert not U.is_newer("abc", "1.0.0")
    assert not U.is_newer("1.0.1", "xyz")
    assert not U.is_newer(None, "1.0.0")


def test_is_prerelease():
    assert U.is_prerelease("v1.0.1-rc1")
    assert U.is_prerelease("1.0.0-beta.2")
    assert not U.is_prerelease("v1.0.0")
    assert not U.is_prerelease("1.0.0")


# ---------- 部署形态 ----------

def test_detect_deployment_source(monkeypatch):
    monkeypatch.delenv("RAG_DEPLOYMENT", raising=False)
    # 源码态（非 frozen、无 /.dockerenv）应为 source
    assert U.detect_deployment() == "source"


def test_detect_deployment_env_override(monkeypatch):
    monkeypatch.setenv("RAG_DEPLOYMENT", "docker")
    assert U.detect_deployment() == "docker"
    monkeypatch.setenv("RAG_DEPLOYMENT", "desktop")
    assert U.detect_deployment() == "desktop"


# ---------- 资源挑选 ----------

def test_pick_asset_prefers_win_x64():
    assets = [
        {"name": "RAG-knowledgebase-v1.0.0-src.zip"},
        {"name": "RAG-knowledgebase-v1.0.0-win-x64.zip"},
    ]
    assert U._pick_asset(assets)["name"].endswith("win-x64.zip")
    assert U._pick_asset([]) is None
    assert U._pick_asset([{"name": "only-src.zip"}]) is None


# ---------- check_update 降级路径 ----------

def _fake_gh(status, data, headers=None, raises=None):
    async def _inner(path, *, params=None, token=None, timeout=20):
        if raises:
            raise raises
        return status, data, (headers or {})
    return _inner


def test_check_update_offline_returns_error(monkeypatch):
    """网络失败 → ok=False + error，且不抛异常（端点不得 500）。"""
    import app.services.skill_search_service as S
    monkeypatch.setattr(S, "_gh_get", _fake_gh(0, None, raises=OSError("network down")))
    U.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(U.check_update())
    assert r["ok"] is False
    assert r["update_available"] is False
    assert "无法连接" in r["error"]
    U.clear_cache()


def test_check_update_rate_limited(monkeypatch):
    import app.services.skill_search_service as S
    monkeypatch.setattr(S, "_gh_get", _fake_gh(403, None, {"x-ratelimit-remaining": "0"}))
    U.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(U.check_update())
    assert r["ok"] is False and "限流" in r["error"]
    U.clear_cache()


def test_check_update_404(monkeypatch):
    import app.services.skill_search_service as S
    monkeypatch.setattr(S, "_gh_get", _fake_gh(404, None))
    U.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(U.check_update())
    assert r["ok"] is False and "未找到" in r["error"]
    U.clear_cache()


def test_check_update_parses_release(monkeypatch):
    import app.services.skill_search_service as S
    payload = {
        "tag_name": "v9.9.9",
        "body": "### 更新内容\n- 修了个大 bug",
        "published_at": "2026-01-01T00:00:00Z",
        "html_url": "https://github.com/241793/RAG-Agent/releases/tag/v9.9.9",
        "prerelease": False,
        "assets": [
            {"name": "RAG-knowledgebase-v9.9.9-src.zip", "size": 1, "digest": "sha256:aa",
             "browser_download_url": "https://github.com/x/src.zip"},
            {"name": "RAG-knowledgebase-v9.9.9-win-x64.zip", "size": 208, "digest": "sha256:bb",
             "browser_download_url": "https://github.com/x/win.zip"},
        ],
    }
    monkeypatch.setattr(S, "_gh_get", _fake_gh(200, payload))
    U.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(U.check_update())
    assert r["ok"] is True
    assert r["latest"] == "9.9.9"
    assert r["update_available"] is True
    assert r["notes"].startswith("### 更新内容")
    assert r["asset"]["name"].endswith("win-x64.zip")
    assert r["asset"]["digest"] == "sha256:bb"
    assert r["current"] == "1.0.0"
    # source 形态不可自更新
    assert r["can_self_update"] is False
    U.clear_cache()


def test_check_update_same_version_no_update(monkeypatch):
    import app.services.skill_search_service as S
    monkeypatch.setattr(S, "_gh_get", _fake_gh(200, {"tag_name": "v1.0.0", "assets": []}))
    U.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(U.check_update())
    assert r["ok"] is True and r["update_available"] is False
    U.clear_cache()


def test_check_update_disabled_skips_network(monkeypatch):
    """关闭检查时不得发起网络请求。"""
    import app.services.skill_search_service as S
    from app.core.config import settings

    called = {"n": 0}

    async def _spy(path, *, params=None, token=None, timeout=20):
        called["n"] += 1
        return 200, {}, {}

    monkeypatch.setattr(S, "_gh_get", _spy)
    monkeypatch.setattr(settings, "update_check_enabled", False)
    U.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(U.check_update())
    assert r["disabled"] is True and r["update_available"] is False
    assert called["n"] == 0
    monkeypatch.setattr(settings, "update_check_enabled", True)
    U.clear_cache()


def test_check_update_cache_hit_avoids_second_call(monkeypatch):
    import app.services.skill_search_service as S
    called = {"n": 0}

    async def _spy(path, *, params=None, token=None, timeout=20):
        called["n"] += 1
        return 200, {"tag_name": "v1.0.0", "assets": []}, {}

    monkeypatch.setattr(S, "_gh_get", _spy)
    U.clear_cache()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(U.check_update())
    r2 = loop.run_until_complete(U.check_update())
    assert called["n"] == 1, "第二次应命中缓存，不再请求"
    assert r2["cached"] is True
    # force 强制刷新
    loop.run_until_complete(U.check_update(force=True))
    assert called["n"] == 2
    U.clear_cache()
