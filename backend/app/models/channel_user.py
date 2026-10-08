"""外部渠道用户 ↔ 本地虚拟 User 的绑定表。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class ChannelUser(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "channel_user"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_channel_user_ext"),
    )

    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # qqbot/wxclaw/wework/feishu
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)  # 本地虚拟 User.id
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 该用户当前会话（渠道内多轮上下文），复用 Conversation
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 用户级知识库覆盖
    agent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 用户选定的智能体
    lang: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 用户语言（/lang 设置，多语言客服）
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 客户备注（客服填写，仅内部可见）
    # 绑定到内部账号：绑定后该外部身份在渠道里继承真实账号的权限（管理员=全权）
    bound_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    bind_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # 一次性绑定码
