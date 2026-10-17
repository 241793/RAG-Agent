"""Docker 在线更新测试：包结构校验、覆盖、备份/回滚、资产选择。

全部离线：用 tmp_path 模拟 /app 与更新包，不真的动容器。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.services import docker_update as D
from app.services import update_service as U


# ---------- 资产选择 ----------

def test_pick_asset_by_deployment():
    assets = [
        {"name": "RAG-knowledgebase-v1.0.1-win-x64.zip", "url": "a"},
        {"name": "RAG-knowledgebase-v1.0.1-docker.zip", "url": "b"},
        {"name": "RAG-knowledgebase-v1.0.1-src.zip", "url": "c"},
    ]
    assert U._pick_asset(assets, "desktop")["url"] == "a"
    assert U._pick_asset(assets, "docker")["url"] == "b"
    # source 形态沿用桌面包判定不适用，但不应抛错
    assert U._pick_asset(assets, "source") is not None


def test_pick_asset_returns_none_when_missing():
    assets = [{"name": "only-src.zip"}]
    assert U._pick_asset(assets, "docker") is None
    assert U._pick_asset(assets, "desktop") is None


# ---------- 覆盖与回滚 ----------

def _make_pkg(root: Path, *, version_tag: str, with_web: bool = True) -> Path:
    """造一个符合约定的更新包目录。"""
    pkg = root / f"pkg-{version_tag}"
    (pkg / "backend" / "app").mkdir(parents=True)
    (pkg / "backend" / "app" / "main.py").write_text(f"# v{version_tag}", encoding="utf-8")
    (pkg / "backend" / "requirements.txt").write_text("", encoding="utf-8")
    if with_web:
        (pkg / "web" / "dist").mkdir(parents=True)
        (pkg / "web" / "dist" / "index.html").write_text(f"<html>{version_tag}</html>", encoding="utf-8")
    (pkg / "CHANGELOG.md").write_text(f"# {version_tag}", encoding="utf-8")
    return pkg


@pytest.fixture
def fake_app(monkeypatch, tmp_path):
    """把 RESOURCE_DIR/BASE_DIR 指到临时目录，模拟容器 /app。"""
    root = tmp_path / "app"
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "main.py").write_text("# old", encoding="utf-8")
    (root / "backend" / "requirements.txt").write_text("", encoding="utf-8")
    (root / "backend" / "data").mkdir(parents=True)
    (root / "web" / "dist").mkdir(parents=True)
    (root / "web" / "dist" / "index.html").write_text("<html>old</html>", encoding="utf-8")

    monkeypatch.setattr(D, "RESOURCE_DIR", root)
    monkeypatch.setattr(D, "BASE_DIR", root / "backend")
    # 跳过真实 pip 安装
    monkeypatch.setattr(D.subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    return root


def test_apply_rejects_bad_package_structure(fake_app, tmp_path):
    """缺 backend/app/main.py 或 web/dist/index.html → 拒绝，且不动现有文件。"""
    pkg = tmp_path / "bad"
    (pkg / "backend").mkdir(parents=True)  # 缺 main.py
    r = D.apply_package(pkg, "1.0.1")
    assert r["ok"] is False
    assert "结构异常" in r["error"]
    # 原文件未被破坏
    assert (fake_app / "backend" / "app" / "main.py").read_text() == "# old"


def test_apply_rejects_missing_webdist(fake_app, tmp_path):
    pkg = _make_pkg(tmp_path, version_tag="1.0.1", with_web=False)
    r = D.apply_package(pkg, "1.0.1")
    assert r["ok"] is False
    assert "web/dist" in r["error"]


def test_apply_overwrites_and_backs_up(fake_app, tmp_path):
    pkg = _make_pkg(tmp_path, version_tag="1.0.1")
    r = D.apply_package(pkg, "1.0.1")
    assert r["ok"] is True, r

    # 覆盖生效
    assert (fake_app / "backend" / "app" / "main.py").read_text() == "# v1.0.1"
    assert "1.0.1" in (fake_app / "web" / "dist" / "index.html").read_text()
    # 数据目录保留
    assert (fake_app / "backend" / "data").is_dir()
    # 备份存在且含旧内容
    backup = Path(r["backup"])
    assert (backup / "backend" / "app" / "main.py").read_text() == "# old"


def test_restore_backup_brings_back_old_content(fake_app, tmp_path):
    pkg = _make_pkg(tmp_path, version_tag="1.0.1")
    r = D.apply_package(pkg, "1.0.1")
    assert r["ok"]
    D.restore_backup(Path(r["backup"]))
    assert (fake_app / "backend" / "app" / "main.py").read_text() == "# old"
    assert "old" in (fake_app / "web" / "dist" / "index.html").read_text()


def test_apply_rolls_back_when_pip_fails(fake_app, tmp_path, monkeypatch):
    """依赖安装失败 → 必须回滚，不能留下半更新状态。"""
    pkg = _make_pkg(tmp_path, version_tag="1.0.1")

    def _fail(*a, **k):
        return type("P", (), {"returncode": 1, "stdout": "", "stderr": "ERROR: no such package"})()

    monkeypatch.setattr(D.subprocess, "run", _fail)
    r = D.apply_package(pkg, "1.0.1")
    assert r["ok"] is False
    assert "已回滚" in r["error"]
    # 回滚后是旧内容
    assert (fake_app / "backend" / "app" / "main.py").read_text() == "# old"
