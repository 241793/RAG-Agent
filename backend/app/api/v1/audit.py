"""审计日志查询接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.middleware.auth_dep import get_current_user, require_permission
from app.models import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    result: str | None = None,
    start: int | None = None,  # 毫秒时间戳
    end: int | None = None,
    user: User = Depends(require_permission("audit:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if start is not None:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end is not None:
        stmt = stmt.where(AuditLog.created_at <= end)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "actor_id": r.actor_id,
                "actor_type": r.actor_type,
                "actor_name": r.actor_name,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "before": r.before,
                "after": r.after,
                "result": r.result,
                "error": r.error,
                "ip": r.ip,
                "user_agent": r.user_agent,
                "request_id": r.request_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
