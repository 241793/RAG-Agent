"""事件订阅（出站 Webhook）：外部系统订阅平台事件，事件发生时平台主动 POST 回调。

与「通知渠道」（NotifyChannel，按业务事件推消息）不同：事件订阅面向**集成**，
把平台事件（ticket.created / document.ready / workflow.completed 等）以 JSON POST
推给外部系统的 URL，带 HMAC 签名供对方校验。
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class EventSubscription(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "event_subscription"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)  # 回调地址
    # 订阅的事件类型（逗号分隔，空 = 全部事件），如 "ticket.created,document.ready"
    events: Mapped[str | None] = mapped_column(String(512), nullable=True)
    secret: Mapped[str | None] = mapped_column(String(256), nullable=True)  # HMAC 密钥（加密存储）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
