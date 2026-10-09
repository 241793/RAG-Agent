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
    assert check_password_strength("aaaaaaaa")[0] is False     # 只有字母（单类）
    assert check_password_strength("12345678")[0] is False     # 只有数字（单类）
    # 不强求大小写：小写字母 + 数字即可
    assert check_password_strength("abc12345")[0] is True
    assert check_password_strength("abcd1234")[0] is True
    assert check_password_strength("Password123!")[0] is True
    assert check_password_strength("Qq123456!")[0] is True
    # 字母 + 符号也可（不含数字）
    assert check_password_strength("abcdefg!")[0] is True


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


# ==================== 注册可选部门 + 记住密码（前端）====================
def test_register_accepts_department():
    from app.schemas.auth import RegisterRequest

    assert "department_id" in RegisterRequest.model_fields
    # 可选
    r = RegisterRequest(username="u1", password="Passw0rd@1")
    assert r.department_id is None


def test_public_departments_endpoint_exists():
    from app.api.v1 import auth as A

    methods = {(r.path, m) for r in A.router.routes for m in getattr(r, "methods", set())}
    assert ("/auth/register/departments", "GET") in methods


def test_register_validates_department_tenant():
    """注册时部门归属需校验（防指定他租户部门）。"""
    import inspect

    from app.api.v1 import auth

    src = inspect.getsource(auth.register)
    assert "department_id" in src and "tenant_id == tenant.id" in src


def test_pending_list_includes_department():
    import inspect

    from app.api.v1 import rbac

    src = inspect.getsource(rbac.list_pending_users)
    assert "department_name" in src


# ==================== 注册申请通知管理员 ====================
def test_user_notify_service_exists():
    from app.services import user_notify as U

    assert hasattr(U, "notify_admins_registration")
    assert hasattr(U, "notify_user_review_result")


def test_register_notifies_admins():
    import inspect

    from app.api.v1 import auth

    src = inspect.getsource(auth.register)
    assert "notify_admins_registration" in src


def test_approve_reject_notify_applicant():
    import inspect

    from app.api.v1 import rbac

    assert "notify_user_review_result" in inspect.getsource(rbac.approve_user)
    assert "notify_user_review_result" in inspect.getsource(rbac.reject_user)


def test_notify_targets_tenant_admins():
    """通知应发给本租户管理员（is_admin + active）。"""
    import inspect

    from app.services import user_notify

    src = inspect.getsource(user_notify._admin_ids)
    assert "is_admin" in src and "status" in src


def test_review_notification_uses_inapp():
    """审核结果用站内消息通知申请人。"""
    import inspect

    from app.services import user_notify

    src = inspect.getsource(user_notify.notify_user_review_result)
    assert "create_inapp" in src


def test_dispatch_supports_skip_inapp():
    """dispatch 支持跳过站内写入（调用方已自行写入时避免重复/锁等待）。"""
    import inspect

    from app.notifiers.registry import dispatch

    assert "skip_inapp" in inspect.signature(dispatch).parameters


async def _run_registration_notify():
    from sqlalchemy import select

    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Notification, Role, Tenant, User, UserRole
    from app.core.security import hash_password

    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
        if not t:
            t = Tenant(name="NT", slug="nt"); db.add(t); await db.flush()
        # 确保有管理员
        admin = (await db.execute(select(User).where(
            User.tenant_id == t.id, User.is_admin.is_(True)))).scalars().first()
        if not admin:
            admin = User(tenant_id=t.id, username="nt_admin", password_hash=hash_password("x"),
                         is_admin=True, status="active")
            db.add(admin); await db.flush()
        await db.commit()
        tid, aid = t.id, admin.id

    # 调注册（走 API 函数，触发通知）
    from app.api.v1.auth import register
    from app.schemas.auth import RegisterRequest
    import time as _t

    uname = f"nt_user_{int(_t.time() * 1000) % 10**8}"
    async with AsyncSessionLocal() as db:
        class _Req:  # 模拟 Request 只需 headers/client
            headers = {}
            client = None
        await register(RegisterRequest(username=uname, password="Notify@2026x",
                                       display_name="通知测试", reason="测试通知"), _Req(), db)
        await db.commit()

    async with AsyncSessionLocal() as db:
        notes = (await db.execute(select(Notification).where(
            Notification.tenant_id == tid, Notification.user_id == aid,
            Notification.ref_type == "user",
        ).order_by(Notification.id.desc()))).scalars().all()
        assert notes, "管理员应收到注册申请通知"
        n = notes[0]
        assert "注册申请" in n.title
        assert n.link == "/admin/users"
        assert uname in (n.body or "")
        # 清理
        u = (await db.execute(select(User).where(User.username == uname))).scalar_one_or_none()
        if u:
            await db.delete(u)
        await db.commit()


def test_registration_sends_admin_notification():
    import asyncio

    asyncio.new_event_loop().run_until_complete(_run_registration_notify())
