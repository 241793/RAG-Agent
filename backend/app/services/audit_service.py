"""审计记录服务。

设计：record_audit(db, ...) 把 AuditLog 对象加入**业务 session**，
随请求的业务事务一起提交（get_db 在请求结束会 commit）。
这样避免 SQLite 独立 session 写锁冲突。

失败操作（业务事务回滚）的审计：用 record_audit_async(...) 开独立 session 写。
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.request_id import (
    actor_name_ctx,
    actor_type_ctx,
    ip_ctx,
    request_id_ctx,
    tenant_id_ctx,
    user_agent_ctx,
    user_id_ctx,
)


def _build(
    *,
    action: str,
    resource_type: str | None = None,
    resource_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    result: str = "success",
    error: str | None = None,
    tenant_id: int | None = None,
    actor_id: int | None = None,
    actor_type: str | None = None,
    actor_name: str | None = None,
) -> dict:
    return {
        "tenant_id": tenant_id if tenant_id is not None else tenant_id_ctx.get(),
        "actor_id": actor_id if actor_id is not None else (user_id_ctx.get() or None),
        "actor_type": actor_type or actor_type_ctx.get(),
        "actor_name": actor_name or actor_name_ctx.get() or None,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "before": before,
        "after": after,
        "result": result,
        "error": error,
        "ip": ip_ctx.get(),
        "user_agent": user_agent_ctx.get(),
        "request_id": request_id_ctx.get(),
        "created_at": int(time.time() * 1000),
    }


def record_audit(db: AsyncSession, **kwargs) -> None:
    """把审计记录加入当前业务 session（随业务事务一起提交）。"""
    from app.models import AuditLog

    db.add(AuditLog(**_build(**kwargs)))


async def record_audit_async(**kwargs) -> None:
    """独立 session 记录审计（用于业务事务已回滚的失败操作，如登录失败）。"""
    from app.core.db import AsyncSessionLocal
    from app.models import AuditLog

    try:
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(**_build(**kwargs)))
            await db.commit()
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger

        get_logger("audit").exception("audit_async_failed")


def snapshot(obj: Any, fields: list[str]) -> dict:
    """取对象白名单字段做快照（写前/写后对比用）。"""
    out = {}
    for f in fields:
        v = getattr(obj, f, None)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[f] = v
    return out


def audited(action: str, resource_type: str, id_arg: str | None = None):
    """装饰器：端点成功返回后，把审计记录加入其 db session（随业务提交）。

    - 从 kwargs 取 `db`（FastAPI 依赖注入的 session）。
    - resource_id：优先返回对象的 .id；否则取路径参数 id_arg。
    - 依赖 get_current_user 已设置 user_id_ctx/tenant_id_ctx。
    """
    import functools

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            result = await fn(*args, **kwargs)
            db = kwargs.get("db")
            rid = getattr(result, "id", None)
            if rid is None and id_arg:
                rid = kwargs.get(id_arg)
            if db is not None:
                record_audit(db, action=action, resource_type=resource_type, resource_id=rid)
            return result

        return wrapper

    return deco
