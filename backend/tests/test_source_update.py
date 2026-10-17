"""源码运行的在线更新测试。

关键回归：覆盖代码时**绝不能动** data/、.env、.venv —— 那是用户数据与运行环境。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import source_update as S


@pytest.fixture
def fake_project(monkeypatch, tmp_path):
    """模拟项目根：backend/（含 data）与 web/dist。"""
    root = tmp_path / "proj"
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "main.py").write_text("# OLD", encoding="utf-8")
    (root / "backend" / "requirements.txt").write_text("", encoding="utf-8")
    # 用户数据与虚拟环境：必须保留
    (root / "backend" / "data").mkdir(parents=True)
    (root / "backend" / "data" / "rag.db").write_text("USER DATA", encoding="utf-8")
    (root / "backend" / ".venv").mkdir(parents=True)
    (root / "backend" / ".venv" / "marker").write_text("KEEP", encoding="utf-8")
    (root / "backend" / ".env").write_text("SECRET=x", encoding="utf-8")
    (root / "web" / "dist").mkdir(parents=True)
    (root / "web" / "dist" / "index.html").write_text("OLD UI", encoding="utf-8")

    monkeypatch.setattr(S, "RESOURCE_DIR", root)
    monkeypatch.setattr(S, "BASE_DIR", root / "backend")
    # 跳过真实 pip
    monkeypatch.setattr(
        S.subprocess, "run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    return root


def _pkg(root: Path, *, tag="1.0.2", with_web=True, with_data=False) -> Path:
    pkg = root / "pkg"
    (pkg / "backend" / "app").mkdir(parents=True)
    (pkg / "backend" / "app" / "main.py").write_text(f"# {tag}", encoding="utf-8")
    (pkg / "backend" / "requirements.txt").write_text("", encoding="utf-8")
    if with_data:
        # 恶意/异常的包若带了 data，也不该覆盖用户的
        (pkg / "backend" / "data").mkdir(parents=True)
        (pkg / "backend" / "data" / "rag.db").write_text("PKG DATA", encoding="utf-8")
    if with_web:
        (pkg / "web" / "dist").mkdir(parents=True)
        (pkg / "web" / "dist" / "index.html").write_text(f"<html>{tag}</html>", encoding="utf-8")
    (pkg / "CHANGELOG.md").write_text(f"# {tag}", encoding="utf-8")
    return pkg


def test_validate_rejects_bad_structure(fake_project, tmp_path):
    pkg = tmp_path / "bad"
    (pkg / "backend").mkdir(parents=True)
    assert S.validate_package(pkg) is not None

    pkg2 = _pkg(tmp_path, with_web=False)
    assert S.validate_package(pkg2) is not None


def test_validate_accepts_good_package(fake_project, tmp_path):
    assert S.validate_package(_pkg(tmp_path)) is None


def test_apply_overwrites_code_and_keeps_user_data(fake_project, tmp_path):
    r = S.apply_package(_pkg(tmp_path, tag="1.0.2"), "1.0.2")
    assert r["ok"] is True, r

    # 代码与前端被覆盖
    assert (fake_project / "backend" / "app" / "main.py").read_text() == "# 1.0.2"
    assert "1.0.2" in (fake_project / "web" / "dist" / "index.html").read_text()

    # ★ 用户数据 / 虚拟环境 / .env 必须原样保留
    assert (fake_project / "backend" / "data" / "rag.db").read_text() == "USER DATA"
    assert (fake_project / "backend" / ".venv" / "marker").read_text() == "KEEP"
    assert (fake_project / "backend" / ".env").read_text() == "SECRET=x"


def test_apply_ignores_data_in_package(fake_project, tmp_path):
    """即使包里带了 data/，也不得覆盖用户的数据库。"""
    r = S.apply_package(_pkg(tmp_path, tag="1.0.3", with_data=True), "1.0.3")
    assert r["ok"] is True, r
    assert (fake_project / "backend" / "data" / "rag.db").read_text() == "USER DATA"


def test_backup_and_restore(fake_project, tmp_path):
    r = S.apply_package(_pkg(tmp_path, tag="1.0.2"), "1.0.2")
    assert r["ok"]
    S.restore_backup(Path(r["backup"]))
    assert (fake_project / "backend" / "app" / "main.py").read_text() == "# OLD"
    assert "OLD UI" in (fake_project / "web" / "dist" / "index.html").read_text()
    # 还原后数据仍在
    assert (fake_project / "backend" / "data" / "rag.db").read_text() == "USER DATA"


def test_pip_failure_rolls_back(fake_project, tmp_path, monkeypatch):
    monkeypatch.setattr(
        S.subprocess, "run",
        lambda *a, **k: type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})(),
    )
    r = S.apply_package(_pkg(tmp_path, tag="1.0.2"), "1.0.2")
    assert r["ok"] is False and "已回滚" in r["error"]
    assert (fake_project / "backend" / "app" / "main.py").read_text() == "# OLD"


def test_backup_dir_unique_on_same_second(fake_project, tmp_path):
    """同一秒多次备份不能撞名（更新重试场景）。"""
    a = S.backup_current("1.0.2")
    b = S.backup_current("1.0.2")
    assert a != b
    assert a.is_dir() and b.is_dir()
