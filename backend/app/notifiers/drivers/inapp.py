"""站内消息渠道：写入 notification 表，供 Header 铃铛展示。"""
from __future__ import annotations

from app.notifiers.base import NotificationMessage
from app.providers.base import ProviderHealth


class InAppNotifier:
    """config: {user_id: 默认收件人（可选，消息自带 user_id 优先）}"""

    def __init__(self, *, tenant_id: int, config: dict | None = None) -> None:
        self.tenant_id = tenant_id
        self.cfg = config or {}

    async def send(self, msg: NotificationMessage) -> bool:
        from app.core.db import AsyncSessionLocal
        from app.models import Notification

        user_id = msg.user_id or self.cfg.get("user_id")
        if not user_id:
            return False
        async with AsyncSessionLocal() as db:
            db.add(Notification(
                tenant_id=self.tenant_id, user_id=int(user_id),
                kind=msg.kind, title=msg.title, body=msg.body, level=msg.level,
                link=msg.link, ref_type=msg.ref_type, ref_id=msg.ref_id, meta=msg.meta or None,
                read=False,
            ))
            await db.commit()
        return True

    async def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, message="站内消息始终可用", latency_ms=0)


async def create_inapp(db, *, tenant_id: int, user_id: int, msg: NotificationMessage) -> int:
    """便捷函数：在已有 session 内直接落一条站内消息（不新开 session）。"""
    from app.models import Notification

    n = Notification(
        tenant_id=tenant_id, user_id=user_id, kind=msg.kind, title=msg.title,
        body=msg.body, level=msg.level, link=msg.link, ref_type=msg.ref_type,
        ref_id=msg.ref_id, meta=msg.meta or None, read=False,
    )
    db.add(n)
    await db.flush()
    return n.id
