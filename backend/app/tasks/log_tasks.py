"""后台：定期清理过期日志备份（按保留天数）。"""
from __future__ import annotations

import time
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("log_cleanup")


def cleanup_logs_once() -> dict:
    """删除超过保留天数的轮转备份文件。返回统计。"""
    from app.core.config import settings

    if not settings.log_file:
        return {"removed": 0}
    p = Path(settings.log_file)
    cutoff = time.time() - settings.log_retention_days * 86400
    removed = 0
    for i in range(1, settings.log_backup_count + 1):
        f = p.with_name(p.name + f".{i}")
        if f.exists() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except Exception:  # noqa: BLE001
                pass
    return {"removed": removed}


async def periodic_log_cleanup(interval_seconds: int = 6 * 3600) -> None:
    """后台循环：定期清理过期日志（供 lifespan 启动）。interval<=0 则关闭。"""
    import asyncio

    if interval_seconds <= 0:
        return
    while True:
        try:
            r = cleanup_logs_once()
            if r.get("removed"):
                logger.info("log_cleanup_done", removed=r["removed"])
        except Exception:  # noqa: BLE001
            logger.exception("log_cleanup_failed")
        await asyncio.sleep(interval_seconds)
