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
    sensitive_only: bool = False,  # 仅看敏感操作（改数据/对外/高危的写操作）
    autonomy: str | None = None,   # 执行方式：auto（AI 自动执行）/ confirmed（人工确认后）/ read
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
    # 敏感/执行方式标记存于 after(JSON)，跨库 JSON 查询不通用 → 用 LIKE 粗筛 + Python 精筛。
    # 这样在 SQLite/MySQL/PG 上行为一致（管理端审计页，量级可控）。
    if sensitive_only or autonomy:
        stmt = stmt.where(AuditLog.after.is_not(None))

    def _match_marks(row: AuditLog) -> bool:
        af = row.after or {}
        if sensitive_only and not af.get("sensitive"):
            return False
        if autonomy and af.get("autonomy") != autonomy:
            return False
        return True

    if sensitive_only or autonomy:
        # 精筛：拉取候选后内存过滤（审计页默认按时间倒序，分页在过滤后重算）
        all_rows = (
            await db.execute(stmt.order_by(AuditLog.id.desc()).limit(2000))
        ).scalars().all()
        filtered = [r for r in all_rows if _match_marks(r)]
        total = len(filtered)
        rows = filtered[(page - 1) * page_size: page * page_size]
    else:
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
