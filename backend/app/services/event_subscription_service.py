"""事件订阅服务：把平台事件推送给外部订阅方（出站 Webhook，带 HMAC 签名）。

复用 notifiers/drivers/webhook.py 的 HTTP 发送能力（含 SSRF 防护）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

from sqlalchemy import select

from app.core.crypto import decrypt
from app.core.logging import get_logger

logger = get_logger("event_sub")

# 平台可订阅的全部事件（供前端下拉/文档用）
KNOWN_EVENTS = [
    "document.ready", "document.failed",
    "ticket.created", "ticket.replied", "ticket.closed", "ticket.rated",
    "ticket.timeout", "ticket.resolved",
    "workflow.completed", "workflow.failed",
]


def _matches(events: str | None, event_name: str) -> bool:
    ev = (events or "").strip()
    if not ev:
        return True
    return event_name in [e.strip() for e in ev.split(",") if e.strip()]


def _sign(secret: str, body: bytes, ts: str) -> str:
    """HMAC-SHA256 签名：对 `{ts}.{body}` 签名（防重放，与主流 webhook 约定一致）。"""
    msg = f"{ts}.".encode() + body
    return "sha256=" + hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


async def _deliver(url: str, secret: str | None, event_name: str, payload: dict, tenant_id: int) -> bool:
    """投递一条事件到订阅 URL。返回是否成功。"""
    import httpx

    from app.connectors.http_guard import assert_safe_url

    body_obj = {
        "event": event_name,
        "tenant_id": tenant_id,
        "ts": int(time.time() * 1000),
        "data": payload or {},
    }
    body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Event": event_name}
    if secret:
        ts = str(int(time.time()))
        headers["X-Timestamp"] = ts
        headers["X-Signature"] = _sign(secret, body, ts)
    try:
        assert_safe_url(url)  # SSRF 防护
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            resp = await c.post(url, headers=headers, content=body)
            resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("event_delivery_failed", url=url, event_name=event_name, err=str(e)[:200])
        return False


async def dispatch_event(event_name: str, *, tenant_id: int, payload: dict | None = None) -> int:
    """把事件推给该租户所有匹配的启用订阅。返回成功投递数（异步不阻塞发布方）。"""
    from app.core.db import AsyncSessionLocal
    from app.models import EventSubscription

    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(EventSubscription).where(
                    EventSubscription.tenant_id == tenant_id,
                    EventSubscription.enabled.is_(True),
                )
            )).scalars().all()
            targets = []
            for s in rows:
                if not _matches(s.events, event_name):
                    continue
                secret = None
                if s.secret:
                    secret = decrypt(s.secret) if s.secret.startswith("enc:") else s.secret
                targets.append((s.url, secret))
    except Exception:  # noqa: BLE001
        logger.exception("event_dispatch_lookup_failed", event_name=event_name)
        return 0

    if not targets:
        return 0

    results = await asyncio.gather(*[
        _deliver(url, secret, event_name, payload or {}, tenant_id)
        for url, secret in targets
    ])
    n = sum(1 for ok in results if ok)
    if n:
        logger.info("event_delivered", event_name=event_name, delivered=n, total=len(targets))
    return n
