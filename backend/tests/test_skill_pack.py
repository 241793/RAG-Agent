"""技能包导入单测：frontmatter 解析、zip 安全校验、GitHub URL 转换。"""
from __future__ import annotations

import io
import zipfile

import pytest

from app.services.skill_pack_service import (
    _parse_frontmatter,
    extract_zip,
    remove_pack_dir,
    resolve_github_zip,
)


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def test_parse_frontmatter():
    text = "---\nname: my-skill\ndescription: 做某事\nversion: 1.2\n---\n正文内容"
    meta, body = _parse_frontmatter(text)
    assert meta["name"] == "my-skill"
    assert meta["description"] == "做某事"
    assert str(meta["version"]) == "1.2"
    assert body.strip() == "正文内容"


def test_parse_frontmatter_none():
    meta, body = _parse_frontmatter("# 没有 frontmatter")
    assert meta == {}
    assert "没有 frontmatter" in body


def test_extract_zip_valid():
    data = _make_zip({
        "SKILL.md": "---\nname: demo\ndescription: 演示技能\n---\n# 说明\n使用方法...",
        "scripts/hello.py": "print('hi')",
        "README.txt": "readme",
    })
    pack = extract_zip(data, tenant_id=1)
    assert pack.name == "demo"
    assert pack.description == "演示技能"
    assert "使用方法" in pack.body_md
    assert len(pack.files) == 3
    assert any(s["name"] == "hello" for s in pack.entry_scripts)
    assert pack.content_hash


def test_extract_zip_path_traversal_blocked():
    data = _make_zip({"../evil.py": "print('bad')"})
    with pytest.raises(ValueError):
        extract_zip(data, tenant_id=1)


def test_extract_zip_bad_zip():
    with pytest.raises(ValueError):
        extract_zip(b"not a zip", tenant_id=1)


def test_resolve_github_zip():
    url = "https://github.com/user/repo"
    out = resolve_github_zip(url)
    assert "codeload.github.com" in out and out.endswith("/zip/refs/heads/main")


def test_resolve_github_already_zip():
    url = "https://example.com/foo.zip"
    assert resolve_github_zip(url) == url


def test_script_description_from_frontmatter():
    data = _make_zip({
        "SKILL.md": "---\nname: demo\nscripts:\n  - name: hello\n    description: 打招呼\n---\n正文",
        "scripts/hello.py": "print('hi')",
    })
    pack = extract_zip(data, tenant_id=1)
    hello = next(s for s in pack.entry_scripts if s["name"] == "hello")
    assert hello["description"] == "打招呼"


def test_script_description_from_manifest():
    data = _make_zip({
        "SKILL.md": "---\nname: demo\n---\n正文",
        "scripts/calc.py": "print(1)",
        "scripts/manifest.json": '{"scripts":[{"name":"calc","description":"计算器"}]}',
    })
    pack = extract_zip(data, tenant_id=1)
    calc = next(s for s in pack.entry_scripts if s["name"] == "calc")
    assert calc["description"] == "计算器"


def test_remove_pack_dir_refuses_outside(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    (tmp_path / "skills").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    # 越界（.. 逃逸）应被拒绝，目录保留
    remove_pack_dir("../outside")
    assert (outside / "keep.txt").exists()


def test_remove_pack_dir_ok(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    target = tmp_path / "skills" / "1" / "abc"
    target.mkdir(parents=True)
    (target / "f.txt").write_text("x", encoding="utf-8")
    remove_pack_dir("1/abc")
    assert not target.exists()


def test_run_pack_script_ok(tmp_path, monkeypatch):
    import asyncio

    from app.core.config import settings
    from app.agents.tools.registry import run_pack_script

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    d = tmp_path / "skills" / "1" / "p"
    d.mkdir(parents=True)
    (d / "echo.py").write_text(
        "import sys, json\n"
        "data = json.loads(sys.stdin.read() or '{}')\n"
        "print(json.dumps({'echo': data.get('x')}))\n",
        encoding="utf-8",
    )
    res = asyncio.new_event_loop().run_until_complete(
        run_pack_script("1/p", "echo.py", {"x": 42})
    )
    assert not res.is_error
    assert '"echo": 42' in res.content


def test_run_pack_script_missing():
    import asyncio

    from app.agents.tools.registry import run_pack_script

    res = asyncio.new_event_loop().run_until_complete(
        run_pack_script("nope/nope", "missing.py", {})
    )
    assert res.is_error


# ---- 从 SKILL.md 原文创建技能包（无需 zip）----
def test_create_pack_from_markdown_with_frontmatter(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.skill_pack_service import create_pack_from_markdown

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    md = "---\nname: demo-x\ndescription: 演示说明\nversion: 1.2\n---\n\n# 正文标题\n\n内容。\n"
    pack = create_pack_from_markdown(md, tenant_id=1)
    assert pack.name == "demo-x"
    assert pack.description == "演示说明"
    assert pack.version == "1.2"
    assert pack.body_md.lstrip().startswith("# 正文标题")
    paths = [f["path"] for f in pack.files]
    assert "SKILL.md" in paths
    # 文件确实落盘
    p = settings.skill_pack_path / pack.pack_dir / "SKILL.md"
    assert p.exists() and p.read_text(encoding="utf-8") == md


def test_create_pack_from_markdown_without_frontmatter(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.skill_pack_service import create_pack_from_markdown

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    pack = create_pack_from_markdown("# 我的技能\n\n正文。", tenant_id=1)
    assert pack.name == "我的技能"  # 退化取一级标题
    assert pack.body_md.lstrip().startswith("# 我的技能")


def test_create_pack_from_markdown_empty_raises(tmp_path, monkeypatch):
    import pytest
    from app.core.config import settings
    from app.services.skill_pack_service import create_pack_from_markdown

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        create_pack_from_markdown("   \n  ", tenant_id=1)


def test_create_pack_from_markdown_extra_scripts(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.skill_pack_service import create_pack_from_markdown

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    md = "---\nname: with-script\n---\n\n# X\n"
    pack = create_pack_from_markdown(
        md, tenant_id=1, extra_files={"scripts/run.py": "print('hi')\n"},
    )
    names = [s["name"] for s in pack.entry_scripts]
    assert "run" in names
    assert (settings.skill_pack_path / pack.pack_dir / "scripts" / "run.py").exists()


def test_create_pack_from_markdown_rejects_traversal(tmp_path, monkeypatch):
    import pytest
    from app.core.config import settings
    from app.services.skill_pack_service import create_pack_from_markdown

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    with pytest.raises(ValueError):
        create_pack_from_markdown(
            "---\nname: bad\n---\n\n# X\n", tenant_id=1,
            extra_files={"../evil.py": "x"},
        )


# ---- 多技能仓库 / 子技能导入 ----
def test_skill_subdirs_detects_multiple(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.skill_pack_service import skill_subdirs

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    data = _make_zip({
        "60s-skills-main/skills/data-query/SKILL.md": "---\nname: data-query\n---\nx",
        "60s-skills-main/skills/weather-query/SKILL.md": "---\nname: weather-query\n---\ny",
        "60s-skills-main/README.md": "readme",
    })
    subs = skill_subdirs(data)
    assert set(subs) == {"skills/data-query", "skills/weather-query"}


def test_extract_zip_multi_without_subpath_raises(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    data = _make_zip({
        "skills/a/SKILL.md": "---\nname: a\n---\nx",
        "skills/b/SKILL.md": "---\nname: b\n---\ny",
    })
    with pytest.raises(ValueError):
        extract_zip(data, tenant_id=1)  # 不再静默取最后一个


def test_extract_zip_subpath_isolates_one_skill(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    data = _make_zip({
        "60s-skills-main/skills/data-query/SKILL.md": "---\nname: data-query\ndescription: 油价汇率\n---\n正文",
        "60s-skills-main/skills/data-query/scripts/run.py": "print(1)\n",
        "60s-skills-main/skills/weather-query/SKILL.md": "---\nname: weather-query\n---\nx",
    })
    pack = extract_zip(data, tenant_id=1, subpath="skills/data-query")
    assert pack.name == "data-query"
    # 摊平到包根
    assert sorted(f["path"] for f in pack.files) == ["SKILL.md", "scripts/run.py"]
    assert [s["name"] for s in pack.entry_scripts] == ["run"]
    # 落盘确实只含选定的子技能
    from app.core.config import settings as s
    base = s.skill_pack_path / pack.pack_dir
    assert (base / "SKILL.md").exists()
    assert (base / "scripts" / "run.py").exists()


def test_extract_zip_single_skill_nested_flattens(tmp_path, monkeypatch):
    """单技能仓库（SKILL.md 在子目录）应自动摊平到根，无需 subpath。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    data = _make_zip({
        "my-skill/SKILL.md": "---\nname: solo\n---\ny",
        "my-skill/ref/data.txt": "x",
    })
    pack = extract_zip(data, tenant_id=1)
    assert pack.name == "solo"
    assert sorted(f["path"] for f in pack.files) == ["SKILL.md", "ref/data.txt"]


def test_extract_zip_subpath_changes_hash(tmp_path, monkeypatch):
    """同一 zip 的不同子技能不能因 hash 相同被去重误判。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path / "skills"))
    data = _make_zip({
        "skills/a/SKILL.md": "---\nname: a\n---\nx",
        "skills/b/SKILL.md": "---\nname: b\n---\ny",
    })
    pa = extract_zip(data, tenant_id=1, subpath="skills/a")
    pb = extract_zip(data, tenant_id=1, subpath="skills/b")
    assert pa.content_hash != pb.content_hash


def test_github_repo_slug_and_default_branch_fallback():
    """resolve_github_zip 只对仓库地址转 main 直链；非仓库地址原样返回。"""
    from app.services.skill_pack_service import _github_repo_slug, resolve_github_zip

    assert _github_repo_slug("https://github.com/a/b") == ("a", "b")
    assert _github_repo_slug("https://github.com/a/b.git") == ("a", "b")
    assert _github_repo_slug("https://example.com/x.zip") is None
    assert resolve_github_zip("https://github.com/a/b").endswith("/zip/refs/heads/main")
    assert resolve_github_zip("https://example.com/x.zip") == "https://example.com/x.zip"


def test_fetch_url_zip_falls_back_across_branches(monkeypatch):
    """默认分支未知时，应在 main/master 间回退，命中 200 的 zip 即返回。"""
    import app.services.skill_pack_service as sps

    async def _no_branch(owner, repo):
        return None  # 模拟查不到默认分支

    monkeypatch.setattr(sps, "_github_default_branch", _no_branch)

    calls = []

    class FakeResp:
        def __init__(self, status, content=b""):
            self.status_code = status
            self.content = content

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            calls.append(url)
            if url.endswith("/main"):
                return FakeResp(404)
            return FakeResp(200, b"PK\x03\x04zipdata")

    # httpx 在函数内 import，patch 其模块属性
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    data = __import__("asyncio").new_event_loop().run_until_complete(
        sps.fetch_url_zip("https://github.com/a/b")
    )
    assert data.startswith(b"PK")
    assert any(u.endswith("/master") for u in calls), "应回退到 master"
