"""鉴权接口：登录 / 注册 / 刷新 / 当前用户。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AuthError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.middleware.auth_dep import get_current_user
from app.models import Department, Role, User, UserRole
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    RoleBrief,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    from app.services.audit_service import record_audit, record_audit_async
    from app.services import login_guard

    # 防爆破第一层：按客户端 IP 限流
    client_ip = _client_ip(request)
    await login_guard.guard_ip(client_ip)
    # 防爆破第二层：账号锁定检查（不提示账号是否存在，统一话术）
    login_guard.ensure_not_locked(body.username)

    result = await db.execute(select(User).where(User.username == body.username))
    users = result.scalars().all()
    # 同名（跨租户）时按密码匹配唯一用户，避免取到错误租户的账号
    user = next((u for u in users if verify_password(body.password, u.password_hash)), None)

    if not user:
        login_guard.record_failure(body.username)
        await record_audit_async(
            action="user.login", resource_type="user", resource_id=body.username,
            result="failure", error="用户名或密码错误", actor_name=body.username,
        )
        # 统一模糊提示，避免用户名枚举
        raise AuthError("用户名或密码错误")

    if getattr(user, "approval_status", "approved") == "pending":
        await record_audit_async(
            action="user.login", resource_type="user", resource_id=user.id,
            result="failure", error="账号待管理员审核", actor_name=user.username,
        )
        raise AuthError("账号正在等待管理员审核，通过后即可登录")
    if getattr(user, "approval_status", "approved") == "rejected":
        await record_audit_async(
            action="user.login", resource_type="user", resource_id=user.id,
            result="failure", error="账号审核未通过", actor_name=user.username,
        )
        raise AuthError("账号审核未通过，请联系管理员")
    if user.status != "active":
        await record_audit_async(
            action="user.login", resource_type="user", resource_id=user.id,
            result="failure", error="账号已停用", actor_name=user.username,
        )
        raise AuthError("账号已停用")

    login_guard.record_success(body.username)
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()
    record_audit(
        db, action="user.login", resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.username,
    )
    tv = int(getattr(user, "token_version", 0) or 0)
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, token_version=tv),
        refresh_token=create_refresh_token(user.id, user.tenant_id, tv),
    )


def _client_ip(request: Request) -> str:
    """取真实客户端 IP（优先反代头，其次 socket）。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else ""


@router.post("/register")
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """自助注册：创建待审核账号，需管理员通过后才能登录。

    安全：IP 限流 + 密码强度校验 + 用户名唯一性；返回统一话术避免账号枚举。
    """
    from app.core.errors import ConflictError
    from app.core.security import validate_password_or_raise
    from app.services import login_guard
    from app.services.audit_service import record_audit_async

    await login_guard.guard_ip(_client_ip(request))
    if not settings.registration_enabled:
        raise AuthError("系统未开放自助注册，请联系管理员开通账号")
    validate_password_or_raise(body.password)

    # 默认落到默认租户（多租户下可由管理员审核时调整）
    from app.models import Tenant

    tenant = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
    if not tenant:
        raise AuthError("系统尚未初始化，请联系管理员")

    exists = (
        await db.execute(
            select(User).where(User.tenant_id == tenant.id, User.username == body.username)
        )
    ).scalar_one_or_none()
    if exists:
        raise ConflictError("用户名已被占用")

    pending = "pending" if settings.require_admin_approval else "approved"
    u = User(
        tenant_id=tenant.id,
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        email=body.email,
        user_type="internal",
        is_admin=False,
        status="active",
        approval_status=pending,
        registered_at=datetime.now(timezone.utc),
        settings=json.dumps({"register_reason": body.reason} if body.reason else {}, ensure_ascii=False),
    )
    db.add(u)
    await db.flush()
    await record_audit_async(
        action="user.register", resource_type="user", resource_id=u.id,
        actor_name=body.username, result="success",
        error=None if pending == "approved" else "待审核",
    )
    if pending == "pending":
        return {"message": "注册成功，请等待管理员审核通过后登录", "pending": True}
    return {"message": "注册成功，请登录", "pending": False}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token)
    except jwt.PyJWTError:
        raise AuthError("刷新凭证无效或已过期")
    if payload.get("type") != "refresh":
        raise AuthError("凭证类型错误")
    user = await db.get(User, int(payload["sub"]))
    if not user or user.status != "active":
        raise AuthError("用户不存在或已停用")
    if getattr(user, "approval_status", "approved") != "approved":
        raise AuthError("账号尚未通过审核")
    # 版本校验：改密码/停用后旧 refresh 也必须失效
    if int(payload.get("tv", 0)) != int(getattr(user, "token_version", 0) or 0):
        raise AuthError("凭证已失效，请重新登录")
    tv = int(getattr(user, "token_version", 0) or 0)
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, token_version=tv),
        refresh_token=create_refresh_token(user.id, user.tenant_id, tv),
    )


@router.get("/me", response_model=UserOut)
async def me(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserOut:
    from app.middleware.auth_dep import get_user_permission_codes

    perms = await get_user_permission_codes(db, user)
    out = UserOut.model_validate(user)
    out.permissions = sorted(perms)
    out.roles = await _user_roles(db, user)
    if user.department_id:
        dept = await db.get(Department, user.department_id)
        out.department_name = dept.name if dept else None
    return out


async def _user_roles(db: AsyncSession, user: User) -> list[RoleBrief]:
    """当前用户的有效角色（跨授予范围，去重）。"""
    rows = (
        await db.execute(
            select(Role.id, Role.code, Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user.id,
                UserRole.tenant_id == user.tenant_id,
            )
        )
    ).all()
    seen: dict[int, RoleBrief] = {}
    for rid, code, name in rows:
        seen.setdefault(rid, RoleBrief(id=rid, code=code, name=name))
    return list(seen.values())


@router.post("/password")
async def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """修改当前用户密码：校验旧密码 + 强度后写入，并使旧 token 全部失效。"""
    from app.core.errors import ValidationError
    from app.core.security import validate_password_or_raise
    from app.services.audit_service import record_audit

    if not verify_password(body.old_password, user.password_hash):
        raise ValidationError("原密码不正确")
    if verify_password(body.new_password, user.password_hash):
        raise ValidationError("新密码不能与原密码相同")
    validate_password_or_raise(body.new_password)
    user.password_hash = hash_password(body.new_password)
    # 强制下线：递增 token 版本，之前签发的 access/refresh 立即失效
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    await db.flush()
    record_audit(
        db, action="user.password_change", resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.username,
    )
    return {"message": "密码已修改，请重新登录"}
