"""通知渠道配置（每租户可配多个渠道）。config 内的密钥经 core.crypto 加密存储。"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class NotifyChannel(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "notify_channel"

    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # inapp/webhook/wecom/dingtalk/smtp
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 含加密后的密钥
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 订阅的事件类型（空 = 全部）；逗号分隔，如 "task.workflow"
    events: Mapped[str | None] = mapped_column(String(128), nullable=True)
