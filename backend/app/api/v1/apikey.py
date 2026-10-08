"""API Key 管理接口：创建（返回明文一次）、列表、吊销。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import get_current_user, require_permission
from app.models import ApiKey, User
from app.services.api_key_service import generate_key
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api-keys", tags=["apikey"])


class ApiKeyCreate(BaseModel):
    name: str
    user_id: int | None = None
    scopes: list[str] = ["chat:use", "retrieval:query"]
    kb_ids: list[int] | None = None
    rate_limit: int = 60
    expires_at: str | None = None  # ISO 字符串，可选


@router.get("")
async def list_api_keys(
    user: User = Depends(require_permission("apikey:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.execute(
            select(ApiKey).where(ApiKey.tenant_id == user.tenant_id).order_by(ApiKey.id.desc())
        )
    ).scalars().all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "user_id": k.user_id,
            "scopes": k.scopes,
            "kb_ids": k.kb_ids,
            "rate_limit": k.rate_limit,
            "status": k.status,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }
        for k in rows
    ]


@router.post("")
async def create_api_key(
    body: ApiKeyCreate,
    user: User = Depends(require_permission("apikey:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw, prefix, key_hash = generate_key()
    from datetime import datetime

    expires = None
    if body.expires_at:
        try:
            expires = datetime.fromisoformat(body.expires_at)
        except ValueError:
            expires = None

    k = ApiKey(
        tenant_id=user.tenant_id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        user_id=body.user_id,
        scopes=body.scopes,
        kb_ids=body.kb_ids,
        rate_limit=body.rate_limit,
        expires_at=expires,
        created_by=user.id,
    )
    db.add(k)
    await db.flush()
    record_audit(db, action="apikey.create", resource_type="api_key", resource_id=k.id)
    # 明文只返回一次
    return {"id": k.id, "name": k.name, "key": raw, "key_prefix": prefix}


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: int,
    user: User = Depends(require_permission("apikey:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    k = await db.get(ApiKey, key_id)
    if not k or k.tenant_id != user.tenant_id:
        raise NotFoundError("API Key 不存在")
    k.status = "revoked"
    k.enabled = False
    await db.flush()
    record_audit(db, action="apikey.revoke", resource_type="api_key", resource_id=key_id)
    return {"message": "已吊销"}
