"""入站 Webhook 令牌：外部系统 POST /hooks/{token} 触发指定定时任务。

token 只存哈希（仿 ApiKey 的 key_hash 模式），明文仅创建时返回一次。
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class WebhookToken(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "webhook_token"

    task_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="默认")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
