"""用量统计接口：按模型/用户/时间聚合 UsageLog。"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.middleware.auth_dep import get_current_user, require_permission
from app.models import ModelConfig, UsageLog, User

router = APIRouter(prefix="/usage", tags=["usage"])


def _today_start_ms() -> int:
    """服务器本地日界的毫秒时间戳。"""
    d = dt.date.today()
    return int(dt.datetime(d.year, d.month, d.day).timestamp() * 1000)


@router.get("/me/today")
async def usage_me_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """当前用户今日消耗（人人可用，只看自己）。"""
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
                func.coalesce(func.sum(UsageLog.cached_tokens), 0),
            ).where(
                UsageLog.user_id == user.id,
                UsageLog.tenant_id == user.tenant_id,
                UsageLog.created_at >= _today_start_ms(),
            )
        )
    ).one()
    return {
        "date": str(dt.date.today()),
        "calls": row[0],
        "prompt_tokens": int(row[1] or 0),
        "completion_tokens": int(row[2] or 0),
        "total_tokens": int(row[3] or 0),
        "cached_tokens": int(row[4] or 0),
    }


@router.get("/summary")
async def usage_summary(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(require_permission("model:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    import time

    since = int((time.time() - days * 86400) * 1000)

    def _agg(*cols):
        return select(*cols).where(UsageLog.tenant_id == user.tenant_id, UsageLog.created_at >= since)

    # 总计
    total = (
        await db.execute(
            _agg(
                func.count().label("calls"),
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                func.coalesce(func.avg(UsageLog.latency_ms), 0),
            )
        )
    ).one()

    # 按模型
    by_model = (
        await db.execute(
            _agg(UsageLog.model_config_id, func.count(), func.sum(UsageLog.prompt_tokens), func.sum(UsageLog.completion_tokens))
            .group_by(UsageLog.model_config_id)
        )
    ).all()
    model_ids = [r[0] for r in by_model if r[0]]
    names = {}
    if model_ids:
        for mc in (await db.execute(select(ModelConfig).where(ModelConfig.id.in_(model_ids)))).scalars().all():
            names[mc.id] = mc.display_name or mc.model_name

    # 按用户
    by_user = (
        await db.execute(
            _agg(UsageLog.user_id, func.count(), func.sum(UsageLog.prompt_tokens), func.sum(UsageLog.completion_tokens))
            .group_by(UsageLog.user_id)
        )
    ).all()
    user_ids = [r[0] for r in by_user if r[0]]
    unames = {}
    if user_ids:
        for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all():
            unames[u.id] = u.display_name or u.username

    # 按天
    by_day = (
        await db.execute(
            _agg(
                func.date(UsageLog.created_at / 1000, "unixepoch"),
                func.count(),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
            )
            .group_by(func.date(UsageLog.created_at / 1000, "unixepoch"))
            .order_by(func.date(UsageLog.created_at / 1000, "unixepoch"))
        )
    ).all()

    return {
        "total": {
            "calls": total[0],
            "prompt_tokens": int(total[1] or 0),
            "completion_tokens": int(total[2] or 0),
            "avg_latency_ms": int(total[3] or 0),
        },
        "by_model": [
            {"model_config_id": r[0], "name": names.get(r[0], f"#{r[0]}"), "calls": r[1],
             "prompt_tokens": int(r[2] or 0), "completion_tokens": int(r[3] or 0)}
            for r in by_model
        ],
        "by_user": [
            {"user_id": r[0], "name": unames.get(r[0], f"#{r[0]}"), "calls": r[1],
             "prompt_tokens": int(r[2] or 0), "completion_tokens": int(r[3] or 0)}
            for r in by_user
        ],
        "by_day": [{"date": str(r[0]), "calls": r[1], "total_tokens": int(r[2] or 0)} for r in by_day],
    }


# ==================== 工具调用统计 ====================
# 数据来源：AuditLog 里 action=chat.tool_call / agent.tool_call（resource_id=工具名，result=success/failure，
# after.latency_ms=耗时）。历史无 latency 的记为 null，只统计上线后数据。
_TOOL_ACTIONS = ("chat.tool_call", "agent.tool_call")


@router.get("/tools")
async def usage_tools(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(require_permission("model:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """工具调用统计：次数/成功率/失败率/平均耗时/最常用工具。"""
    import time as _time

    from sqlalchemy import case

    from app.models import AuditLog

    since = int((_time.time() - days * 86400) * 1000)
    base = [AuditLog.tenant_id == user.tenant_id,
            AuditLog.action.in_(_TOOL_ACTIONS),
            AuditLog.created_at >= since]

    # 总量
    tot = (await db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((AuditLog.result == "success", 1), else_=0)), 0),
        ).where(*base)
    )).one()
    total = int(tot[0] or 0)
    success = int(tot[1] or 0)

    # 按工具
    rows = (await db.execute(
        select(
            AuditLog.resource_id,
            func.count(),
            func.coalesce(func.sum(case((AuditLog.result == "success", 1), else_=0)), 0),
        ).where(*base).group_by(AuditLog.resource_id).order_by(func.count().desc())
    )).all()

    # 平均耗时（从 after JSON 取 latency_ms；仅 SQLite 支持 json_extract，其它库降级为 None）
    lat_map: dict = {}
    try:
        from app.core.config import settings as _st

        if _st.is_sqlite:
            lat_rows = (await db.execute(
                select(
                    AuditLog.resource_id,
                    func.avg(func.json_extract(AuditLog.after, "$.latency_ms")),
                ).where(*base).group_by(AuditLog.resource_id)
            )).all()
            lat_map = {r[0]: (int(r[1]) if r[1] is not None else None) for r in lat_rows}
    except Exception:  # noqa: BLE001
        lat_map = {}

    by_tool = []
    for r in rows:
        name, calls, ok = r[0], int(r[1] or 0), int(r[2] or 0)
        by_tool.append({
            "tool": name,
            "calls": calls,
            "success": ok,
            "failure": calls - ok,
            "success_rate": round(ok / calls, 3) if calls else None,
            "avg_latency_ms": lat_map.get(name),
        })

    # 按天
    by_day = (await db.execute(
        select(
            func.date(AuditLog.created_at / 1000, "unixepoch"),
            func.count(),
        ).where(*base).group_by(func.date(AuditLog.created_at / 1000, "unixepoch"))
        .order_by(func.date(AuditLog.created_at / 1000, "unixepoch"))
    )).all()

    return {
        "total": total,
        "success": success,
        "failure": total - success,
        "success_rate": round(success / total, 3) if total else None,
        "by_tool": by_tool,
        "by_day": [{"date": str(d), "calls": int(c or 0)} for d, c in by_day],
    }
