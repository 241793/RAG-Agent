"""更新日志服务测试：解析、兜底、缓存。全部离线。"""
from __future__ import annotations

import asyncio

from app.services import changelog_service as C


SAMPLE = """# 更新日志

这是说明文字。

## [1.0.1] - 2026-10-20

### 新增

- 更新日志滚动条，所有用户可见
- 支持 [多版本历史](https://example.com)

### 修复

- Docker 部署的更新指引不清晰

## [1.0.0] - 2026-10-15

### 新增

- 首发版本
"""


# ---------- 解析 ----------

def test_parse_basic():
    vs = C.parse_changelog(SAMPLE)
    assert len(vs) == 2
    assert vs[0]["version"] == "1.0.1"
    assert vs[0]["date"] == "2026-10-20"
    assert vs[1]["version"] == "1.0.0"
    titles = [s["title"] for s in vs[0]["sections"]]
    assert titles == ["新增", "修复"]
    assert vs[0]["sections"][0]["items"][0] == "更新日志滚动条，所有用户可见"
    assert vs[0]["sections"][1]["items"] == ["Docker 部署的更新指引不清晰"]


def test_parse_ignores_preamble_and_h1():
    """文档开头的一级标题与说明文字不得被当成版本块。"""
    vs = C.parse_changelog(SAMPLE)
    assert all(v["version"] not in ("更新日志",) for v in vs)
    assert len(vs) == 2


def test_parse_unreleased_and_no_date():
    text = "## [Unreleased]\n### 新增\n- 进行中\n"
    vs = C.parse_changelog(text)
    assert vs[0]["version"] == "Unreleased"
    assert vs[0]["date"] is None
    assert vs[0]["sections"][0]["items"] == ["进行中"]


def test_parse_items_before_any_section():
    """条目出现在分组标题之前 → 归入「变更」，不得丢失。"""
    vs = C.parse_changelog("## [2.0.0] - 2026-01-01\n- 没有分组标题的条目\n")
    assert vs[0]["sections"][0]["title"] == "变更"
    assert vs[0]["sections"][0]["items"] == ["没有分组标题的条目"]


def test_parse_empty_and_garbage():
    assert C.parse_changelog("") == []
    assert C.parse_changelog("随便一段没有标题的文字\n- 一个条目\n") == []


def test_parse_tolerates_bullet_styles():
    text = "## [1.0.0]\n### 修复\n- 短横条目\n* 星号条目\n"
    items = C.parse_changelog(text)[0]["sections"][0]["items"]
    assert items == ["短横条目", "星号条目"]


def test_parse_version_without_brackets():
    vs = C.parse_changelog("## 1.2.3 - 2026-02-02\n- x\n")
    assert vs[0]["version"] == "1.2.3"
    assert vs[0]["date"] == "2026-02-02"


# ---------- markdown 清理 ----------

def test_strip_markdown_link_and_bold():
    assert C._strip_markdown_link("见 [文档](https://x.com) 说明") == "见 文档 说明"
    assert C._strip_markdown_link("**加粗** 与 `代码`") == "加粗 与 代码"


# ---------- 本地优先 / 兜底 ----------

def test_get_changelog_prefers_local(monkeypatch, tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(C, "RESOURCE_DIR", tmp_path)
    C.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(C.get_changelog())
    assert r["source"] == "local"
    assert r["latest"]["version"] == "1.0.1"
    assert len(r["history"]) == 2
    # 链接已被清理
    assert "https://example.com" not in str(r["latest"])
    C.clear_cache()


def test_get_changelog_falls_back_to_release(monkeypatch, tmp_path):
    """本地没有文件时，用 GitHub Release 正文兜底。"""
    monkeypatch.setattr(C, "RESOURCE_DIR", tmp_path)  # 空目录，无 CHANGELOG.md
    import app.services.update_service as U

    async def _fake_check(*a, **k):
        return {"ok": True, "latest": "9.9.9", "notes": "### 新增\n- 来自 Release 的内容",
                "published_at": "2026-03-03", "html_url": "https://github.com/x/releases/tag/v9.9.9"}

    monkeypatch.setattr(U, "check_update", _fake_check)
    C.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(C.get_changelog())
    assert r["source"] == "release"
    assert r["latest"]["version"] == "9.9.9"
    assert r["latest"]["sections"][0]["items"] == ["来自 Release 的内容"]
    assert r["latest"]["url"].endswith("v9.9.9")
    C.clear_cache()


def test_get_changelog_none_when_nothing_available(monkeypatch, tmp_path):
    """两处都拿不到时 → source=none + 空列表（不臆造内容）。"""
    monkeypatch.setattr(C, "RESOURCE_DIR", tmp_path)
    import app.services.update_service as U

    async def _fake_check(*a, **k):
        return {"ok": False, "error": "offline"}

    monkeypatch.setattr(U, "check_update", _fake_check)
    C.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(C.get_changelog())
    assert r["source"] == "none"
    assert r["latest"] is None
    assert r["history"] == []
    assert r["ok"] is True
    C.clear_cache()


def test_get_changelog_never_raises_on_bad_file(monkeypatch, tmp_path):
    """文件损坏（非法编码）也不得抛异常。"""
    (tmp_path / "CHANGELOG.md").write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setattr(C, "RESOURCE_DIR", tmp_path)
    import app.services.update_service as U

    async def _fake_check(*a, **k):
        return {"ok": False}

    monkeypatch.setattr(U, "check_update", _fake_check)
    C.clear_cache()
    r = asyncio.new_event_loop().run_until_complete(C.get_changelog())
    assert r["ok"] is True
    C.clear_cache()


def test_get_changelog_cached(monkeypatch, tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(C, "RESOURCE_DIR", tmp_path)
    C.clear_cache()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(C.get_changelog())
    r2 = loop.run_until_complete(C.get_changelog())
    assert r2["cached"] is True
    C.clear_cache()


def test_real_repo_changelog_parses():
    """仓库自带的 CHANGELOG.md 必须能被解析（防止格式写坏）。"""
    from app.core.config import RESOURCE_DIR

    f = RESOURCE_DIR / "CHANGELOG.md"
    if not f.is_file():
        return  # 打包/测试环境无此文件时跳过
    vs = C.parse_changelog(f.read_text(encoding="utf-8"))
    assert vs, "仓库 CHANGELOG.md 应至少解析出一个版本块"
    from app.core.config import settings

    assert any(v["version"] == settings.app_version for v in vs), (
        f"CHANGELOG.md 应包含当前版本 {settings.app_version} 的段落"
    )
