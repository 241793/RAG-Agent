"""SSO 接口：登录跳转、回调、配置管理、可用提供者列表。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.middleware.auth_dep import require_permission
from app.models import SsoConfig, User, UserRole
from app.services.audit_service import record_audit
from app.services.sso_providers import (
    build_authorize_url,
    exchange_and_profile,
    new_state,
    pkce_pair,
)

router = APIRouter(prefix="/auth/sso", tags=["sso"])

# 内存态 state/verifier 暂存（进程内；生产建议 Redis）
_STATE: dict[str, dict] = {}
_STATE_TTL = 600


def _prune() -> None:
    now = time.time()
    for k in [k for k, v in _STATE.items() if now - v["ts"] > _STATE_TTL]:
        _STATE.pop(k, None)


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """公开：返回已启用的 SSO 提供者（供登录页渲染按钮）。"""
    rows = (
        await db.execute(select(SsoConfig).where(SsoConfig.enabled.is_(True)))
    ).scalars().all()
    return [{"provider": r.provider, "name": r.name or r.provider} for r in rows]


@router.get("/{provider}/login")
async def sso_login(provider: str, db: AsyncSession = Depends(get_db)):
    cfg = (
        await db.execute(
            select(SsoConfig).where(SsoConfig.provider == provider, SsoConfig.enabled.is_(True))
        )
    ).scalars().first()
    if not cfg:
        raise NotFoundError(f"未启用的 SSO 提供者: {provider}")

    _prune()
    state = new_state()
    verifier, _ = pkce_pair()
    redirect_uri = cfg.redirect_uri or _default_redirect()
    _STATE[state] = {"verifier": verifier, "provider": provider, "ts": time.time()}
    url = await build_authorize_url(cfg, state, redirect_uri, verifier)
    return RedirectResponse(url)


@router.get("/{provider}/callback")
async def sso_callback(
    provider: str,
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    cfg = (
        await db.execute(
            select(SsoConfig).where(SsoConfig.provider == provider, SsoConfig.enabled.is_(True))
        )
    ).scalars().first()
    if not cfg:
        raise NotFoundError(f"未启用的 SSO 提供者: {provider}")

    st = _STATE.pop(state, None)
    if not st:
        raise NotFoundError("SSO state 无效或已过期")

    redirect_uri = cfg.redirect_uri or _default_redirect()
    profile = await exchange_and_profile(cfg, code, redirect_uri, st["verifier"])

    # JIT：按 (provider, subject) 找用户，找不到则创建
    user = (
        await db.execute(
            select(User).where(
                User.sso_provider == provider, User.sso_subject == profile.subject
            )
        )
    ).scalar_one_or_none()
    if not user:
        if not cfg.auto_create_user:
            raise NotFoundError("用户不存在且未开启自动创建")
        tenant_id = cfg.tenant_id
        username = profile.username or profile.subject
        # 用户名冲突加后缀
        exists = (
            await db.execute(select(User).where(User.tenant_id == tenant_id, User.username == username))
        ).scalar_one_or_none()
        if exists:
            username = f"{username}_{profile.subject[:6]}"
        user = User(
            tenant_id=tenant_id,
            username=username,
            password_hash=hash_password(new_state()),  # 随机密码，SSO 用户不依赖密码登录
            display_name=profile.display_name or username,
            email=profile.email,
            sso_provider=provider,
            sso_subject=profile.subject,
        )
        db.add(user)
        await db.flush()
        # 默认角色
        for rid in cfg.default_role_ids or []:
            db.add(
                UserRole(
                    tenant_id=tenant_id, user_id=user.id, role_id=rid,
                    scope_type="tenant", scope_id=0,
                )
            )
        record_audit(
            db, action="user.sso_create", resource_type="user", resource_id=user.id,
            tenant_id=tenant_id, actor_id=user.id, actor_name=username, actor_type="system",
        )

    user.last_login_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    await db.flush()
    record_audit(
        db, action="user.login", resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, actor_id=user.id, actor_name=user.username,
    )

    access = create_access_token(user.id, user.tenant_id)
    refresh = create_refresh_token(user.id, user.tenant_id)
    # 用 URL fragment 传 token（不进服务端日志）
    frontend = _frontend_base()
    return RedirectResponse(f"{frontend}/login#access_token={access}&refresh_token={refresh}")


def _default_redirect() -> str:
    return f"{_backend_base()}/api/v1/auth/sso"


def _backend_base() -> str:
    return f"http://127.0.0.1:{settings.port}"


def _frontend_base() -> str:
    origins = settings.cors_origin_list
    return origins[0] if origins else f"http://127.0.0.1:{settings.port}"


# ==================== 配置管理 ====================
@router.get("/configs/all")
async def list_configs(
    user: User = Depends(require_permission("sso:read")), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = (
        await db.execute(select(SsoConfig).where(SsoConfig.tenant_id == user.tenant_id))
    ).scalars().all()
    return [
        {
            "id": c.id, "provider": c.provider, "name": c.name, "enabled": c.enabled,
            "client_id": c.client_id, "authorize_url": c.authorize_url,
            "token_url": c.token_url, "userinfo_url": c.userinfo_url,
            "corp_id": c.corp_id, "agent_id": c.agent_id, "redirect_uri": c.redirect_uri,
        }
        for c in rows
    ]


@router.post("/configs")
async def upsert_config(
    body: dict,
    user: User = Depends(require_permission("sso:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    provider = body.get("provider")
    cfg = (
        await db.execute(
            select(SsoConfig).where(SsoConfig.tenant_id == user.tenant_id, SsoConfig.provider == provider)
        )
    ).scalars().first()
    if not cfg:
        cfg = SsoConfig(tenant_id=user.tenant_id, provider=provider)
        db.add(cfg)
    for k in (
        "name", "enabled", "client_id", "client_secret", "authorize_url", "token_url",
        "userinfo_url", "jwks_uri", "issuer", "scopes", "agent_id", "corp_id",
        "redirect_uri", "attribute_map", "default_role_ids", "auto_create_user", "sync_dept",
    ):
        if k in body:
            setattr(cfg, k, body[k])
    await db.flush()
    record_audit(db, action="sso.config", resource_type="sso_config", resource_id=cfg.id)
    return {"id": cfg.id, "message": "已保存"}
