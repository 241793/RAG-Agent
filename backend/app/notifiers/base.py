"""通知渠道抽象 —— 与 connectors/ 同风格（Protocol + dataclass）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.providers.base import ProviderHealth


@dataclass
class NotificationMessage:
    """一条待发送的通知。title 必填，其余可选。"""

    title: str
    body: str = ""
    level: str = "info"          # info/success/warning/error
    kind: str = "system"         # system/task/workflow/chat
    link: str | None = None      # 前端路由
    ref_type: str | None = None
    ref_id: int | None = None
    user_id: int | None = None   # 站内消息收件人
    meta: dict = field(default_factory=dict)


@runtime_checkable
class NotifyChannelProvider(Protocol):
    async def send(self, msg: NotificationMessage) -> bool: ...

    async def health(self) -> ProviderHealth: ...
