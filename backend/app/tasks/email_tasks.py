"""后台：定时轮询邮件入库源，拉取新邮件入库。"""
from __future__ import annotations

from sqlalchemy import select

from app.core.logging import get_logger

logger = get_logger("email_poll")


async def poll_email_sources_once() -> dict:
    """拉取一次所有启用的邮件源。返回统计。"""
    from app.core.db import AsyncSessionLocal
    from app.models import EmailSource
    from app.services.email_ingest_service import sync_source

    total = 0
    n = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(EmailSource).where(EmailSource.enabled.is_(True), EmailSource.status != "disabled")
        )).scalars().all()
        for s in rows:
            try:
                r = await sync_source(db, s)
                if r.get("ok"):
                    n += 1
                    total += int(r.get("ingested") or 0)
                await db.commit()
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception("email_poll_one_failed", source_id=s.id)
    if total:
        logger.info("email_poll_done", sources=n, ingested=total)
    return {"sources": n, "ingested": total}


async def periodic_email_poll(interval_seconds: int = 300) -> None:
    """后台循环：定期轮询邮件源（供 lifespan 启动）。interval<=0 则关闭。"""
    import asyncio

    if interval_seconds <= 0:
        return
    while True:
        try:
            await poll_email_sources_once()
        except Exception:  # noqa: BLE001
            logger.exception("email_poll_failed")
        await asyncio.sleep(interval_seconds)
