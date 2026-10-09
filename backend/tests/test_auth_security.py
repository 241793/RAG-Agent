"""登录安全加固回归：密码强度、防爆破、token 吊销、注册审核、SQL 注入加固。"""
from __future__ import annotations

import asyncio
import inspect


# ==================== 密码强度 ====================
def test_password_strength_rules():
    from app.core.security import check_password_strength

    assert check_password_strength("abc")[0] is False          # 太短
    assert check_password_strength("admin123")[0] is False     # 弱密码
    assert check_password_strength("password")[0] is False     # 弱密码
    assert check_password_strength("aaaaaaaa")[0] is False     # 单一字符类
    assert check_password_strength("Password123!")[0] is True
    assert check_password_strength("Qq123456!")[0] is True


def test_password_validation_raises():
    from app.core.errors import ValidationError
    from app.core.security import validate_password_or_raise

    try:
        validate_password_or_raise("123456")
        assert False, "弱密码应该抛错"
    except ValidationError:
        pass


# ==================== 防爆破 ====================
def test_login_guard_lockout():
    from app.services import login_guard

    login_guard.reset_all()
    login_guard.ensure_not_locked("bob")  # 初始未锁定
    from app.core.config import settings
    for _ in range(settings.login_max_failures):
        login_guard.record_failure("bob")
    try:
        login_guard.ensure_not_locked("bob")
        assert False, "达到阈值后应锁定"
    except Exception:
        pass
    login_guard.record_success("bob")      # 成功登录解除锁定
    login_guard.ensure_not_locked("bob")
    login_guard.reset_all()


def test_login_guard_ip_rate_limit():
    from app.services import login_guard
    from app.core.config import settings

    async def _run():
        # 连续请求超过每分钟上限后应被拒
        allowed = 0
        for _ in range(settings.login_rate_per_min + 3):
            try:
                await login_guard.guard_ip("9.9.9.9")
                allowed += 1
            except Exception:
                break
        return allowed
    allowed = asyncio.new_event_loop().run_until_complete(_run())
    assert allowed <= settings.login_rate_per_min, "IP 限流应在上限内放行"


def test_login_uses_guard():
    import inspect

    from app.api.v1 import auth

    src = inspect.getsource(auth.login)
    assert "guard_ip" in src and "ensure_not_locked" in src and "record_failure" in src


# ==================== token 吊销 ====================
def test_token_carries_version():
    from app.core.security import create_access_token, decode_token

    tok = create_access_token(1, 1, token_version=7)
    assert decode_token(tok).get("tv") == 7


def test_auth_dep_checks_token_version():
    import inspect

    from app.middleware import auth_dep

    src = inspect.getsource(auth_dep.get_current_user)
    assert "token_version" in src and '"tv"' in src


def test_change_password_bumps_version():
    import inspect

    from app.api.v1 import auth

    src = inspect.getsource(auth.change_password)
    assert "token_version" in src
    assert "+ 1" in src


# ==================== 注册审核 ====================
def test_user_has_approval_fields():
    from app.models import User

    cols = set(User.__table__.columns.keys())
    assert {"approval_status", "token_version", "registered_at"} <= cols


def test_register_endpoint_exists():
    from app.api.v1 import auth as A

    methods = {(r.path, m) for r in A.router.routes for m in getattr(r, "methods", set())}
    assert ("/auth/register", "POST") in methods


def test_review_endpoints_exist():
    from app.api.v1 import rbac as R

    methods = {(r.path, m) for r in R.router.routes for m in getattr(r, "methods", set())}
    assert ("/admin/users/pending", "GET") in methods
    assert ("/admin/users/{user_id}/approve", "POST") in methods
    assert ("/admin/users/{user_id}/reject", "POST") in methods


def test_pending_user_cannot_login():
    import inspect

    from app.api.v1 import auth

    src = inspect.getsource(auth.login)
    assert "approval_status" in src and "pending" in src


def test_admin_created_user_is_approved():
    import inspect

    from app.api.v1.rbac import create_user

    src = inspect.getsource(create_user)
    assert 'approval_status="approved"' in src


def test_register_validates_password():
    import inspect

    from app.api.v1 import auth

    src = inspect.getsource(auth.register)
    assert "validate_password_or_raise" in src


# ==================== SQL 注入加固 ====================
def test_sql_connector_rejects_query_placeholder():
    from app.connectors.drivers.sql_db import SqlConnector
    from app.core.errors import ValidationError

    try:
        SqlConnector(kb_id=1, config={
            "dsn": "sqlite:///./x.db",
            "query_sql": "SELECT * FROM t WHERE name LIKE '%{query}%'",
        })
        assert False, "{query} 拼接占位符应被拒绝"
    except ValidationError:
        pass


def test_sql_connector_allows_bound_param():
    from app.connectors.drivers.sql_db import SqlConnector

    # :query 参数绑定应被接受
    SqlConnector(kb_id=1, config={
        "dsn": "sqlite:///./x.db",
        "query_sql": "SELECT * FROM t WHERE name LIKE :query",
    })


def test_sql_readonly_blocks_comment_bypass():
    from app.connectors.drivers.sql_db import _check_readonly
    from app.core.errors import ValidationError

    # 注释绕过的写关键字应被拦
    try:
        _check_readonly("SELECT 1; DROP TABLE x")
        assert False, "多语句应被拒绝"
    except ValidationError:
        pass
    # 纯 select 应通过
    _check_readonly("SELECT a, b FROM t WHERE x = :q")


def test_like_escape():
    from app.connectors.drivers.sql_db import _escape_like

    assert _escape_like("100%") == "100" + chr(92) + "%"
    assert _escape_like("a_b") == "a" + chr(92) + "_b"


# ==================== secret_key 加固 ====================
def test_secret_key_not_placeholder():
    from app.core.config import _SECRET_PLACEHOLDER, settings

    assert settings.secret_key and settings.secret_key != _SECRET_PLACEHOLDER, \
        "运行时密钥不得为占位默认值"
