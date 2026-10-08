"""后台：定期对启用的 Provider 做健康检查，回写 health_status/last_check_at。"""
from __future__ import annotations

import time

from app.core.logging import get_logger

logger = get_logger("health")


async def check_all_providers() -> int:
    """遍历 active Provider 逐个健康检查（chat 用途）。返回检查数。"""
    from sqlalchemy import select

    from app.core.db import AsyncSessionLocal
    from app.models import ModelProvider
    from app.providers.registry import _build_driver

    checked = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ModelProvider).where(ModelProvider.status == "active")
        )).scalars().all()
        for p in rows:
            try:
                drv = _build_driver(p.kind, p.base_url, p.api_key, p.timeout, p.extra_headers)
                try:
                    h = await drv.health(purpose="chat")
                except TypeError:
                    h = await drv.health()
                p.health_status = "ok" if getattr(h, "ok", False) else "fail"
            except Exception:  # noqa: BLE001
                p.health_status = "fail"
            p.last_check_at = int(time.time() * 1000)
            checked += 1
        await db.commit()
    return checked


async def periodic_health_check(interval_seconds: int = 1800) -> None:
    """后台循环：定期健康检查（供 lifespan 启动）。间隔 <=0 则跳过。"""
    import asyncio

    from app.core.config import settings

    if interval_seconds <= 0:
        return
    # 启动后先等一会，避免与初始化抢资源
    await asyncio.sleep(30)
    while True:
        try:
            n = await check_all_providers()
            logger.info("provider_health_checked", count=n)
        except Exception:  # noqa: BLE001
            logger.exception("provider_health_check_failed")
        await asyncio.sleep(interval_seconds)
