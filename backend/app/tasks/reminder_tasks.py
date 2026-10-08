"""待办提醒轮询：周期扫描到期待办并推送。"""
from __future__ import annotations

import asyncio

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger("reminder_task")


async def reminder_check_once() -> int:
    from app.services.reminder_service import scan_due_reminders

    async with AsyncSessionLocal() as db:
        try:
            return await scan_due_reminders(db)
        except Exception:  # noqa: BLE001
            logger.exception("reminder_check_failed")
            return 0


async def periodic_reminder_check(interval_seconds: int = 60) -> None:
    while True:
        try:
            await asyncio.sleep(max(interval_seconds, 30))
            await reminder_check_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("reminder_loop_error")
