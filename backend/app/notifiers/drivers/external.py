"""外部渠道通知出口：把通知发到已接入的 IM 渠道（QQ/微信/企微/飞书）。

复用 channels 的长连接 adapter（channel_manager.send），而非新建连接。
config：{channel_id: int, target: str, target_type: "group"|"user"}
  target_type=group → OutboundMessage.group_id=target；=user → user_id=target。

限制：wxclaw（非官方微信）依赖 24h 内互动产生的 context_token，无法冷启动推送；
QQ 主动消息有频次限制；企微/飞书主动推送最可靠。
"""
from __future__ import annotations

import time

from app.notifiers.base import NotificationMessage
from app.providers.base import ProviderHealth


class ExternalChannelNotifier:
    def __init__(self, *, tenant_id: int = 0, config: dict | None = None) -> None:
        self.tenant_id = tenant_id
        self.cfg = config or {}
        self.channel_id = int(self.cfg.get("channel_id") or 0)
        self.target = str(self.cfg.get("target") or "").strip()
        self.target_type = (self.cfg.get("target_type") or "group").lower()
        self.kind = str(self.cfg.get("kind") or "").strip() or None  # 渠道类型（可选，用于 id 失效时兜底）

    def _build_out(self, msg: NotificationMessage):
        from app.channels.base import OutboundMessage

        text = msg.title if not msg.body else f"{msg.title}\n{msg.body}"
        if msg.link:
            text = f"{text}\n{msg.link}"
        kwargs = {"group_id": self.target} if self.target_type == "group" else {"user_id": self.target}
        return OutboundMessage(content=text, **kwargs)

    async def send(self, msg: NotificationMessage) -> bool:
        if not self.channel_id or not self.target:
            return False
        from app.channels.manager import channel_manager

        return await channel_manager.send_with_fallback(self.channel_id, self.kind, self._build_out(msg))

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        if not self.channel_id:
            return ProviderHealth(ok=False, message="未选择外部渠道", latency_ms=0)
        if not self.target:
            return ProviderHealth(ok=False, message="未填写接收对象 id", latency_ms=0)
        from app.channels.manager import channel_manager

        connected = channel_manager.is_connected(self.channel_id)
        return ProviderHealth(
            ok=connected,
            message="渠道已连接，可推送" if connected else "渠道未连接/未启用，暂时无法推送",
            latency_ms=int((time.time() - t0) * 1000),
        )
