"""后台：定期轮询个人邮箱账号，拉取新邮件到收件箱（+ 可选入库）。"""
from __future__ import annotations

from sqlalchemy import select

from app.core.logging import get_logger

logger = get_logger("mail_poll")


async def poll_mail_accounts_once() -> dict:
    """拉取一次所有启用的邮箱账号。返回统计。"""
    from app.core.db import AsyncSessionLocal
    from app.models import MailAccount
    from app.services.mail_service import poll_account

    total = 0
    n = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(MailAccount).where(MailAccount.enabled.is_(True), MailAccount.status != "disabled")
        )).scalars().all()
        for a in rows:
            try:
                r = await poll_account(db, a)
                if r.get("ok"):
                    n += 1
                    total += int(r.get("new") or 0)
                await db.commit()
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception("mail_poll_one_failed", account_id=a.id)
    if total:
        logger.info("mail_poll_done", accounts=n, new=total)
    return {"accounts": n, "new": total}


async def periodic_mail_poll(interval_seconds: int = 300) -> None:
    """后台循环：定期轮询邮箱账号（供 lifespan 启动）。interval<=0 则关闭。"""
    import asyncio

    if interval_seconds <= 0:
        return
    while True:
        try:
            await poll_mail_accounts_once()
        except Exception:  # noqa: BLE001
            logger.exception("mail_poll_failed")
        await asyncio.sleep(interval_seconds)
