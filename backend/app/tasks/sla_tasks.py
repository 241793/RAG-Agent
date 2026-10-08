"""后台：定期扫描客服工单 SLA 超时（首次响应超时 → 标记 + 通知）。"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("service_sla")


async def sla_check_once() -> int:
    """扫描一次超时工单，返回命中数。"""
    from app.core.db import AsyncSessionLocal
    from app.services.service_ticket_service import scan_sla_breaches

    async with AsyncSessionLocal() as db:
        try:
            n = await scan_sla_breaches(db)
            if n:
                logger.info("sla_breaches_marked", count=n)
            return n
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("sla_check_failed")
            return 0


async def periodic_sla_check(interval_seconds: int = 300) -> None:
    """后台循环：定期扫描 SLA（供 lifespan 启动）。interval<=0 则关闭。"""
    import asyncio

    if interval_seconds <= 0:
        return
    while True:
        try:
            await sla_check_once()
        except Exception:  # noqa: BLE001
            logger.exception("sla_loop_error")
        await asyncio.sleep(interval_seconds)
