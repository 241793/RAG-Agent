"""HITL 审批动作的启动恢复：修复「approved 但从未 executed」的卡死动作。

背景：审批端点先 CAS 把状态置 approved 并 commit，随后在**另一个 session**里执行工具再置
executed。若进程在这两步之间崩溃（或执行协程异常），动作会永久停在 approved——
既没执行、前端也看不到（不是 pending）、又不会有结果。这里在启动时兜底：
把「approved 且超过宽限期仍未 executed」的动作标记为 failed，给出明确原因，
让用户知道该操作未生效、需重新发起。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.logging import get_logger

logger = get_logger("hitl_recover")

# 宽限期：approved 后多久仍未 executed 视为卡死（含正常执行中的缓冲）
STUCK_GRACE = timedelta(minutes=10)


async def recover_stuck_actions(db, *, now: datetime | None = None) -> int:
    """把卡在 approved 的动作标记为 failed。返回修复条数。

    注意：AgentAction.created_at 是 DATETIME（TimestampMixin），比较须用 datetime。
    """
    from app.models import AgentAction

    now = now or datetime.now(timezone.utc)
    cutoff = now - STUCK_GRACE
    rows = (await db.execute(
        select(AgentAction).where(
            AgentAction.status == "approved",
            AgentAction.created_at <= cutoff,
        )
    )).scalars().all()
    if not rows:
        return 0
    ids = [a.id for a in rows]
    await db.execute(
        update(AgentAction)
        .where(AgentAction.id.in_(ids), AgentAction.status == "approved")
        .values(status="failed", error="审批通过后执行中断（进程重启），请重新发起该操作")
    )
    await db.commit()
    logger.warning("hitl_stuck_recovered", count=len(ids), ids=ids[:20])
    return len(ids)
