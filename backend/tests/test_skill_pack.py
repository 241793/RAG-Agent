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


def test_node_script_discovery():
    """Node 技能：入口脚本位于 tools/*.mjs（不止 scripts/*.py），应被识别为 node 运行时。"""
    data = _make_zip({
        "SKILL.md": "---\nname: ppt-gen\n---\n# 说明",
        "package.json": '{"name":"ppt-gen","type":"module"}',
        "tools/build_all.mjs": "console.log('build')",
        "tools/check_deck.mjs": "console.log('check')",
        "core/helper.mjs": "export const x=1",  # core/ 不是入口目录，不应收录
    })
    pack = extract_zip(data, tenant_id=1)
    names = {s["name"]: s for s in pack.entry_scripts}
    assert "build_all" in names and names["build_all"]["runtime"] == "node"
    assert names["build_all"]["path"] == "tools/build_all.mjs"
    assert "check_deck" in names
    assert "helper" not in names, "非入口目录的脚本不应收录"


def test_shell_and_scripts_dir_runtime():
    """scripts/ 下的 .py 与 .sh 都应收录，运行时分别标记。"""
    data = _make_zip({
        "SKILL.md": "---\nname: demo\n---\n正文",
        "scripts/run.py": "print(1)",
        "scripts/setup.sh": "echo hi",
    })
    pack = extract_zip(data, tenant_id=1)
    by = {s["name"]: s["runtime"] for s in pack.entry_scripts}
    assert by.get("run") == "python"
    assert by.get("setup") == "sh"


def test_collect_artifacts_filters_intermediate(tmp_path):
    """产物捕获：只保留成品（pptx/html），剔除中间报告与隐藏临时目录。"""
    from app.agents.tools.ops_tools2 import RunSkillScriptTool

    root = tmp_path / "pack"
    root.mkdir()
    (root / "deck.pptx").write_bytes(b"P" * 100)
    (root / "deck.preview.html").write_text("<html></html>", encoding="utf-8")
    (root / "deck.build.json").write_text("{}", encoding="utf-8")   # 中间文件
    (root / "deck.report.json").write_text("{}", encoding="utf-8")  # 中间文件
    (root / "src.md").write_text("源", encoding="utf-8")            # 有成品时忽略纯文本
    hidden = root / ".ppt-build-tmp"
    hidden.mkdir()
    (hidden / "inner.pptx").write_bytes(b"X")                      # 隐藏临时目录
    nm = root / "node_modules"
    nm.mkdir()
    (nm / "dep.pptx").write_bytes(b"Y")                            # 依赖目录

    got = RunSkillScriptTool()._collect_artifacts(root, since_ts=0)
    names = set(got)
    assert "deck.pptx" in names and "deck.preview.html" in names
    assert "deck.build.json" not in names and "deck.report.json" not in names
    assert "src.md" not in names, "有二进制/预览成品时忽略纯文本"
    assert "inner.pptx" not in names and "dep.pptx" not in names


async def test_run_pack_script_python_runtime(tmp_path, monkeypatch):
    """Python 脚本：从 stdin 读 JSON 参数并回显。"""
    from app.core.config import settings
    from app.agents.tools.registry import run_pack_script

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path))
    d = tmp_path / "1" / "pack"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "echo.py").write_text(
        "import json,sys; a=json.load(sys.stdin); print(json.dumps({'got': a.get('x')}))",
        encoding="utf-8",
    )
    res = await run_pack_script("1/pack", "scripts/echo.py", {"x": 42})
    assert not res.is_error, res.content
    assert '"got": 42' in res.content


async def test_run_pack_script_path_escape_blocked(tmp_path, monkeypatch):
    """越界脚本路径应被拒绝。"""
    from app.core.config import settings
    from app.agents.tools.registry import run_pack_script

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path))
    (tmp_path / "1" / "pack").mkdir(parents=True)
    res = await run_pack_script("1/pack", "../../outside.py", {})
    assert res.is_error and "不存在" in res.content


async def test_python_sandbox_allows_site_packages(tmp_path, monkeypatch):
    """关键回归：Python 沙箱不能用 -S（会屏蔽 site-packages → 技能无法导入第三方库）。

    用一个必然存在于 site-packages 的第三方模块（pip 自带的 packaging）验证。
    """
    from app.core.config import settings
    from app.agents.tools.registry import run_pack_script

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path))
    d = tmp_path / "1" / "pack"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "imp.py").write_text(
        "try:\n    import packaging; ok=True\n"
        "except Exception as e:\n    ok=False; print('ERR', e)\n"
        "print('SITE_OK' if ok else 'SITE_FAIL')\n",
        encoding="utf-8",
    )
    res = await run_pack_script("1/pack", "scripts/imp.py", {})
    assert "SITE_OK" in res.content, res.content


async def test_manifest_drives_entrypoints_and_args(tmp_path, monkeypatch):
    """清单驱动：entrypoints 的 runtime/args/outputs 生效；positional 模式把参数放 argv。"""
    from app.core.config import settings
    from app.agents.tools.registry import run_pack_script
    from app.services.skill_runtime import load_manifest, scan_entry_scripts

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path))
    d = tmp_path / "1" / "pack"
    (d / "tools").mkdir(parents=True)
    (d / "tools" / "build.py").write_text(
        "import sys\nprint('ARGV', sys.argv[1:])\n", encoding="utf-8")
    (d / "skill.yaml").write_text(
        "runtime: python\n"
        "entrypoints:\n"
        "  - name: build\n"
        "    path: tools/build.py\n"
        "    args: positional\n"
        "    outputs: ['*.pptx']\n"
        "permissions:\n  platform_tools: [http_request]\n",
        encoding="utf-8",
    )
    mf = load_manifest(d)
    assert mf.runtime == "python"
    assert mf.permissions.get("platform_tools") == ["http_request"]
    eps = scan_entry_scripts(d, manifest=mf)
    assert eps[0]["name"] == "build" and eps[0]["outputs"] == ["*.pptx"]
    res = await run_pack_script("1/pack", "tools/build.py", {},
                                extra_args=["deck.json", "-o", "out"], entry=eps[0])
    assert not res.is_error, res.content
    assert "deck.json" in res.content and "-o" in res.content, res.content


def test_explicit_outputs_collect(tmp_path):
    """清单声明 outputs 时按其 glob 精确收产物。"""
    from app.agents.tools.ops_tools2 import RunSkillScriptTool

    root = tmp_path / "pack"
    (root / "out").mkdir(parents=True)
    (root / "out" / "a.pptx").write_bytes(b"A")
    (root / "unrelated.json").write_text("{}", encoding="utf-8")
    got = RunSkillScriptTool()._collect_artifacts(root, since_ts=0, outputs=["out/*.pptx"])
    assert set(got) == {"a.pptx"}, set(got)


def test_bridge_token_roundtrip():
    """桥接令牌：type=skill、携带工具白名单、可解码。"""
    from app.core.security import create_skill_token, decode_token

    tok = create_skill_token(tenant_id=7, user_id=3, skill_id=10,
                             allowed_tools=["knowledge_retrieval"])
    p = decode_token(tok)
    assert p["type"] == "skill" and p["skill_id"] == 10 and p["tenant_id"] == 7
    assert p["allowed_tools"] == ["knowledge_retrieval"]


def test_child_env_whitelist_blocks_secrets():
    """环境隔离：后端密钥/DB连接串不得传给技能脚本；PATH 等必需项保留。"""
    from app.services import skill_runtime as sr

    base = {
        "PATH": "/usr/bin", "SECRET_KEY": "leak-me", "DATABASE_URL": "sqlite:///x",
        "OPENAI_API_KEY": "sk-leak", "ANTHROPI_AUTH_TOKEN": "PROXY_MANAGED",
        "MY_RANDOM": "nope", "LANG": "zh_CN.UTF-8",
    }
    rt = sr.get_runtime("python")
    env = sr.build_child_env(runtime=rt, base=base, extra={"PPT_SKILL_ARGS": "{}"})
    assert env.get("PATH") == "/usr/bin" and env.get("LANG") == "zh_CN.UTF-8"
    assert "SECRET_KEY" not in env and "DATABASE_URL" not in env
    assert "OPENAI_API_KEY" not in env and "ANTHROPI_AUTH_TOKEN" not in env
    assert "MY_RANDOM" not in env
    assert env.get("PYTHONNOUSERSITE") == "1" and env.get("PPT_SKILL_ARGS") == "{}"


async def test_entry_timeout_enforced(tmp_path, monkeypatch):
    """入口 timeout 生效：睡 30s 的脚本在 3s 被终止。"""
    import time

    from app.core.config import settings
    from app.agents.tools.registry import run_pack_script

    monkeypatch.setattr(settings, "skill_pack_dir", str(tmp_path))
    d = tmp_path / "1" / "pack"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "slow.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    t0 = time.time()
    res = await run_pack_script("1/pack", "scripts/slow.py", {}, entry={"timeout": 3})
    assert res.is_error and "超时" in res.content, res.content
    assert time.time() - t0 < 12, "应在超时后很快返回"


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
