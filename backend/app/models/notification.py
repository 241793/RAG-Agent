"""站内消息通知。字段为后续「内部聊天」预留 sender_id / thread_id。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Notification(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "notification"

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)  # 收件人
    # system / task / workflow / chat（chat 供后续内部聊天）
    kind: Mapped[str] = mapped_column(String(16), default="system", index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="info")  # info/success/warning/error
    link: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 前端路由
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # scheduled_task/workflow/...
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 为「内部聊天」预留：发送者与线程（本轮不启用）
    sender_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    thread_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
