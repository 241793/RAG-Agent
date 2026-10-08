"""技能搜索服务：关键词映射、查询构造、GitHub 搜索解析、限流处理。

全部用 mock（不依赖真实网络）：`_gh_get` 被 monkeypatch 替代。
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import skill_search_service as S


# ---------------- 纯函数：关键词映射 ----------------
def test_map_keywords_hits_table():
    terms = S.map_keywords("油价")
    assert any("fuel" in t.lower() for t in terms)


def test_map_keywords_ascii_passthrough():
    assert S.map_keywords("weather") == ["weather"]


def test_map_keywords_unknown_chinese_fallback():
    # 未命中映射表 → 原词兜底
    assert S.map_keywords("量子计算") == ["量子计算"]


def test_map_keywords_empty():
    assert S.map_keywords("") == []
    assert S.map_keywords("   ") == []


# ---------------- 纯函数：查询构造 ----------------
def test_build_queries_never_contains_skill_md_literal():
    """回归防呆：绝对不能把 SKILL.md 当搜索词（实测会毁掉召回）。"""
    qs = S.build_queries(S.map_keywords("油价"))
    assert qs, "应产出查询"
    assert not any("SKILL.md" in q for q in qs)


def test_build_queries_bounded():
    qs = S.build_queries(["a", "b", "c", "d"])
    assert len(qs) <= 3


# ---------------- search_github 解析（mock _gh_get）----------------
def _fake_gh(items, *, status=200, headers=None):
    async def _fn(path, *, params=None, token=None, timeout=20):
        return status, {"total_count": len(items), "items": items}, (headers or {})
    return _fn


def test_search_skills_parses_candidates(monkeypatch):
    async def _gh(path, *, params=None, token=None, timeout=20):
        if "/search/repositories" in path:
            return 200, {"total_count": 1, "items": [
                {"full_name": "vikiboss/60s-skills", "description": "含油价 API",
                 "stargazers_count": 47, "html_url": "https://github.com/vikiboss/60s-skills"},
            ]}, {}
        # tree API → 返回含 SKILL.md 的结构
        return 200, {"tree": [
            {"path": "skills/data-query/SKILL.md"}, {"path": "README.md"},
        ]}, {}

    monkeypatch.setattr(S, "_gh_get", _gh)
    r = asyncio.new_event_loop().run_until_complete(S.search_skills("油价", limit=5))
    assert r["error"] is None
    assert r["candidates"]
    top = r["candidates"][0]
    assert top.repo == "vikiboss/60s-skills"
    assert "skills/data-query" in top.sub_skills


def test_search_skills_rate_limited(monkeypatch):
    async def _gh(path, *, params=None, token=None, timeout=20):
        return 403, {"message": "rate limited"}, {"x-ratelimit-remaining": "0"}

    monkeypatch.setattr(S, "_gh_get", _gh)
    r = asyncio.new_event_loop().run_until_complete(S.search_skills("油价", limit=5))
    assert r["error"] and ("限流" in r["error"] or "rate" in r["error"].lower())


def test_search_skills_skill_repos_ranked_first(monkeypatch):
    """真技能仓库（star 低但含 SKILL.md）应排在 star 高但非技能的仓库之前。"""
    async def _gh(path, *, params=None, token=None, timeout=20):
        if "/search/repositories" in path:
            return 200, {"total_count": 2, "items": [
                {"full_name": "ethgas/ethgas", "description": "Ethereum gas oracle",
                 "stargazers_count": 9999, "html_url": "https://github.com/ethgas/ethgas"},
                {"full_name": "acme/fuel-skill", "description": "fuel price skill",
                 "stargazers_count": 1, "html_url": "https://github.com/acme/fuel-skill"},
            ]}, {}
        if "fuel-skill" in path:
            return 200, {"tree": [{"path": "SKILL.md"}]}, {}
        return 200, {"tree": [{"path": "src/main.py"}]}, {}  # ethgas 无 SKILL.md

    monkeypatch.setattr(S, "_gh_get", _gh)
    r = asyncio.new_event_loop().run_until_complete(S.search_skills("油价", limit=5))
    assert r["candidates"][0].repo == "acme/fuel-skill"


def test_search_skills_empty_keywords():
    r = asyncio.new_event_loop().run_until_complete(S.search_skills("", limit=5))
    assert r["error"]


# ---------------- find_skill 工具 ----------------
def test_find_skill_tool_empty_keywords():
    from app.agents.tools.ops_tools2 import FindSkillTool
    from app.agents.tools.base import ToolContext

    tool = FindSkillTool()
    assert tool.kind == "read"
    ctx = ToolContext(db=None, ps=None, tenant_id=1, user_id=1)
    res = asyncio.new_event_loop().run_until_complete(tool.run({"keywords": ""}, ctx))
    assert res.is_error


def test_find_skill_tool_returns_candidates(monkeypatch):
    from app.agents.tools.ops_tools2 import FindSkillTool
    from app.agents.tools.base import ToolContext

    async def _fake_search(kw, *, token=None, limit=5, **kw2):
        return {"candidates": [
            S.Candidate(repo="acme/fuel-skill", description="油价", stars=3,
                        html_url="https://github.com/acme/fuel-skill", sub_skills=["fuel"]),
        ], "mapped_terms": ["fuel price"], "error": None, "note": None}

    monkeypatch.setattr(S, "search_skills", _fake_search)
    tool = FindSkillTool()
    ctx = ToolContext(db=None, ps=None, tenant_id=1, user_id=1)
    res = asyncio.new_event_loop().run_until_complete(tool.run({"keywords": "油价"}, ctx))
    assert not res.is_error
    assert "acme/fuel-skill" in res.content
    assert res.data["count"] == 1
