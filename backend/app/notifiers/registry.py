"""通知渠道注册表 + 派发（与 connectors/registry.py 同构）。

dispatch：查该租户启用的渠道（按事件过滤）→ 并发发送 → 单渠道失败不阻断。
站内消息（inapp）始终可用，即使未配置渠道也应写入（保证 Header 铃铛有内容）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.core.errors import ValidationError
from app.notifiers.base import NotificationMessage

_SECRET_KEYS = ("password", "secret", "token", "api_key", "key")


def _decrypt_config(cfg: dict | None) -> dict:
    cfg = dict(cfg or {})
    for k in list(cfg.keys()):
        if any(s in k.lower() for s in _SECRET_KEYS) and isinstance(cfg[k], str) and cfg[k].startswith("enc:"):
            cfg[k] = decrypt(cfg[k])
    return cfg


def build_notifier(kind: str, *, tenant_id: int, config: dict | None):
    cfg = _decrypt_config(config)
    if kind == "inapp":
        from app.notifiers.drivers.inapp import InAppNotifier

        return InAppNotifier(tenant_id=tenant_id, config=cfg)
    if kind == "webhook":
        from app.notifiers.drivers.webhook import WebhookNotifier

        return WebhookNotifier(config=cfg)
    if kind in ("wecom", "dingtalk"):
        from app.notifiers.drivers.wecom import WecomNotifier

        return WecomNotifier(config=cfg, kind=kind)
    if kind == "smtp":
        from app.notifiers.drivers.smtp import SmtpNotifier

        return SmtpNotifier(config=cfg)
    if kind == "external":
        from app.notifiers.drivers.external import ExternalChannelNotifier

        return ExternalChannelNotifier(tenant_id=tenant_id, config=cfg)
    raise ValidationError(f"不支持的通知渠道: {kind}")


def _matches_events(channel, kind: str) -> bool:
    ev = (channel.events or "").strip()
    if not ev:
        return True
    return kind in [e.strip() for e in ev.split(",") if e.strip()]


async def dispatch(
    db: AsyncSession, *, tenant_id: int, msg: NotificationMessage, user_id: int | None = None,
    skip_inapp: bool = False,
) -> dict:
    """把通知派发到该租户所有启用且匹配事件的渠道。返回 {渠道kind: 成功与否}。

    user_id：站内消息的默认收件人（msg.user_id 优先）。
    skip_inapp：跳过站内消息写入（调用方已自行写入站内消息时用，避免重复/锁等待）。
    """
    import asyncio

    from app.core.logging import get_logger
    from app.models import NotifyChannel

    log = get_logger("notifier")
    if msg.user_id is None and user_id is not None:
        msg.user_id = user_id

    rows = (
        await db.execute(
            select(NotifyChannel).where(
                NotifyChannel.tenant_id == tenant_id, NotifyChannel.enabled.is_(True)
            )
        )
    ).scalars().all()
    # 站内消息总是要写（若配了收件人），即使没有渠道记录
    has_inapp = any(r.kind == "inapp" for r in rows)

    targets: list[tuple[str, Any]] = []
    for r in rows:
        if skip_inapp and r.kind == "inapp":
            continue
        if _matches_events(r, msg.kind):
            try:
                targets.append((r.kind, build_notifier(r.kind, tenant_id=tenant_id, config=r.config)))
            except Exception as e:  # noqa: BLE001
                log.warning("notifier_build_failed", kind=r.kind, err=str(e)[:200])

    if not has_inapp and msg.user_id and not skip_inapp:
        from app.notifiers.drivers.inapp import InAppNotifier

        targets.append(("inapp", InAppNotifier(tenant_id=tenant_id, config={"user_id": msg.user_id})))

    if not targets:
        return {}

    async def _one(kind: str, ch) -> tuple[str, bool]:
        try:
            return kind, await ch.send(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("notify_failed", kind=kind, err=str(e)[:200])
            return kind, False

    results = await asyncio.gather(*[_one(k, c) for k, c in targets])
    return dict(results)
