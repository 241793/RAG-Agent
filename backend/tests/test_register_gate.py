"""自助注册：状态端点、开关控制、校验。

注册端点本身已在 test_auth_security.py 覆盖校验细节；本文件聚焦
「注册开关」这一新增行为，以及公开状态端点的契约。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

c = TestClient(app)


def test_register_status_shape():
    """公开端点：返回 enabled / require_approval，登录页据此决定是否显示入口。"""
    r = c.get("/api/v1/auth/register/status")
    assert r.status_code == 200
    d = r.json()
    assert set(d.keys()) == {"enabled", "require_approval"}
    assert isinstance(d["enabled"], bool)
    assert isinstance(d["require_approval"], bool)


def test_register_disabled_blocks_submission(monkeypatch):
    """关闭注册时不得创建账号。"""
    monkeypatch.setattr(settings, "registration_enabled", False)
    r = c.get("/api/v1/auth/register/status")
    assert r.json()["enabled"] is False

    r = c.post("/api/v1/auth/register", json={"username": "zz_probe_off", "password": "Probe12345!"})
    assert r.status_code >= 400
    assert "未开放" in str(r.json())


def test_register_departments_empty_when_disabled(monkeypatch):
    """关闭注册时部门端点返回空数组（不泄露组织结构）。"""
    monkeypatch.setattr(settings, "registration_enabled", False)
    r = c.get("/api/v1/auth/register/departments")
    assert r.status_code == 200
    assert r.json() == []


def test_default_registration_is_closed():
    """默认必须是关闭：公网部署时避免被随意注册。

    注意：本测试依赖未被其它测试污染的默认值；settings 是进程级单例，
    若其它测试修改过需自行还原（现有测试均用 monkeypatch，会自动还原）。
    """
    from app.core.config import Settings

    assert Settings.model_fields["registration_enabled"].default is False


def test_register_status_reflects_toggle(monkeypatch):
    monkeypatch.setattr(settings, "registration_enabled", True)
    monkeypatch.setattr(settings, "require_admin_approval", False)
    d = c.get("/api/v1/auth/register/status").json()
    assert d["enabled"] is True
    assert d["require_approval"] is False
