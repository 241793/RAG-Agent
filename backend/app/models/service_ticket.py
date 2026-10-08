"""客服工单：当 AI 无法解决（用户请求转人工/命中关键词）时生成，指派给人工客服跟进。

闭环：渠道用户请求转人工 → 建工单 + 通知客服 → 客服在后台回复 → 回发到原渠道 → 关闭。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class ServiceTicket(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "service_ticket"

    # open(待处理) / pending(处理中) / resolved(已解决) / closed(已关闭)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # low/normal/high/urgent
    subject: Mapped[str] = mapped_column(String(512), default="")
    # 分类与标签（企业级工单）
    category: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 来源渠道（可空：来自问答页/手动创建/对外 API）
    channel_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    channel_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="channel")  # channel|api|manual|qa
    # 外部用户标识 + 会话（用于把客服回复回发到原渠道）
    external_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 建单用户（问答页发起时的登录用户）
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    # 消息流： [{role: user|assistant|agent, content, ts}]
    messages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 内部备注（仅客服可见，不发给客户）
    internal_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_message_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    closed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)  # 解决说明
    # ---- SLA / 时效（企业级）----
    first_response_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sla_due_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    # ---- 满意度（CSAT）----
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    satisfaction_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 提醒开关：该工单有新回复时是否通知客服（默认开）
    watch: Mapped[bool] = mapped_column(Boolean, default=True)
    # ---- 跨境：客户语言 / 时区 / 币种（时区币种预留）----
    customer_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    customer_tz: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)


class ServiceTicketQuickReply(Base, IdMixin, TimestampMixin, TenantMixin):
    """客服快捷回复（话术库）：预存话术，客服回复时一键引用。"""

    __tablename__ = "service_ticket_quick_reply"

    title: Mapped[str] = mapped_column(String(128), nullable=False)  # 话术标题（列表展示）
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 话术正文
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 分类（可选）
    scope: Mapped[str] = mapped_column(String(16), default="global")  # global=全租户 | personal=个人
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
