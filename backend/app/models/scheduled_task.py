"""定时任务：到点触发一段提示词（Agent）或运行一个工作流。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class ScheduledTask(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "scheduled_task"

    owner_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)  # 目标智能体
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    target_type: Mapped[str] = mapped_column(String(16), default="prompt")  # prompt | workflow
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)  # prompt 目标用
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # workflow 目标用
    schedule_kind: Mapped[str] = mapped_column(String(16), default="cron")  # cron | interval | once
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # once 的一次性触发时刻（ms）
    # 触发方式：schedule=按时间；event=按事件（如 document.ready）
    trigger_kind: Mapped[str] = mapped_column(String(16), default="schedule")
    event_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 失败重试
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 通知时机：always 总是 / success 仅成功 / fail 仅失败 / never 从不
    notify_on: Mapped[str] = mapped_column(String(16), default="fail")
    timezone: Mapped[str] = mapped_column(String(32), default="Asia/Shanghai")
    next_run_at: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)  # ms
    last_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # success|failed|running
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # WorkflowRun.id
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 专属会话
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    # 依赖链：本任务在本任务成功后自动触发（A→B）。NULL = 无依赖。
    depends_on_task_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    depends_on_status: Mapped[str] = mapped_column(String(16), default="success")  # 前置需 success 才触发
