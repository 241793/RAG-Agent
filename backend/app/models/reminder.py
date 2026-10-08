"""待办 / 日程 / 提醒：真实持久化的提醒实体（区别于「定时任务跑提示词」）。"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Reminder(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "reminder"

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)  # 到期时刻（ms）
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | done
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)  # 负责人
    creator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | scheduled
    # 重复：cron 表达式（如 "0 9 * * *" = 每天 9 点）；空=不重复
    repeat_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remind_before_minutes: Mapped[int] = mapped_column(Integer, default=0)  # 提前多少分钟提醒
    notify_on_due: Mapped[bool] = mapped_column(Boolean, default=True)
    notified_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 上次提醒时刻（防重复推送）
    done_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
