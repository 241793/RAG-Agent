"""鉴权接口：登录 / 刷新 / 当前用户。"""
from __future__ import annotations

from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends
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
    RoleBrief,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    from app.services.audit_service import record_audit, record_audit_async

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        await record_audit_async(
            action="user.login", resource_type="user", resource_id=body.username,
            result="failure", error="用户名或密码错误", actor_name=body.username,
        )
        raise AuthError("用户名或密码错误")
    if user.status != "active":
        await record_audit_async(
            action="user.login", resource_type="user", resource_id=user.id,
            result="failure", error="账号已停用", actor_name=user.username,
        )
        raise AuthError("账号已停用")
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()
    record_audit(
        db, action="user.login", resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.username,
    )
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id),
        refresh_token=create_refresh_token(user.id, user.tenant_id),
    )


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
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id),
        refresh_token=create_refresh_token(user.id, user.tenant_id),
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
    """修改当前用户密码：校验旧密码后写入新密码。"""
    from app.core.errors import ValidationError
    from app.services.audit_service import record_audit

    if not verify_password(body.old_password, user.password_hash):
        raise ValidationError("原密码不正确")
    if len(body.new_password) < 6:
        raise ValidationError("新密码至少 6 位")
    user.password_hash = hash_password(body.new_password)
    await db.flush()
    record_audit(
        db, action="user.password_change", resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.username,
    )
    return {"message": "密码已修改"}
