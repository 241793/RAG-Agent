"""产物生命周期：过期清理。"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.ingest.storage import get_storage

logger = get_logger("artifact")


async def cleanup_expired_artifacts(db: AsyncSession) -> int:
    """删除已过期产物（文件 + 记录），返回清理数量。"""
    from app.models import Artifact

    now_ms = int(time.time() * 1000)
    rows = (
        await db.execute(
            select(Artifact).where(Artifact.expires_at.isnot(None), Artifact.expires_at < now_ms)
        )
    ).scalars().all()
    storage = get_storage()
    n = 0
    for art in rows:
        try:
            storage.delete(art.file_key)
        except Exception:  # noqa: BLE001
            pass
        await db.delete(art)
        n += 1
    if n:
        await db.commit()
        logger.info("artifacts_cleaned", count=n)
    return n


async def periodic_cleanup(interval_seconds: int = 6 * 3600) -> None:
    """后台循环：定期清理过期产物（供 lifespan 启动）。"""
    import asyncio

    from app.core.db import AsyncSessionLocal

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with AsyncSessionLocal() as db:
                await cleanup_expired_artifacts(db)
        except Exception:  # noqa: BLE001
            logger.exception("artifact_cleanup_failed")
