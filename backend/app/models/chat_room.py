"""企业聊天室：房间、成员、消息。

与 AI 问答的 Conversation/Message 分离——后者带 UsageLog/上下文压缩/单属主语义，
不适用于「人与人」的多成员聊天。仅复用附件存储与签名 URL 机制。
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class ChatRoom(Base, IdMixin, TimestampMixin, TenantMixin):
    """聊天室。kind: group=群聊（含默认大群）/ direct=一对私聊。"""

    __tablename__ = "chat_room"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="group", index=True)  # group/direct
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # 默认大群（全员可见）
    announcement: Mapped[str | None] = mapped_column(Text, nullable=True)  # 群公告（置顶展示）
    # 私聊时存对方 user_id（direct 房间按 (user_a,user_b) 唯一）
    peer_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 扩展：绑定的机器人 {agent_id: {name, ...}} 等
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_message_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 毫秒
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/archived

    __table_args__ = (
        Index("ix_chat_room_direct", "tenant_id", "peer_user_id"),
    )


class ChatRoomMember(Base, IdMixin, TenantMixin, TimestampMixin):
    """房间成员。role: owner=群主 / admin=群管理员 / member=普通成员。

    principal 支持把「机器人」也加进群：principal_type=agent 时 principal_id=Agent.id。
    """

    __tablename__ = "chat_room_member"

    room_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)  # 人类成员
    # 机器人成员：principal_type=agent + principal_id=Agent.id
    agent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner/admin/member
    muted_until: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 禁言到期（毫秒）
    last_read_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 已读水位（毫秒）
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_chat_member_room_user"),
    )


class ChatMessage(Base, IdMixin, TenantMixin):
    """聊天消息。撤回用软删（revoked + 保留占位），置顶用 pinned。"""

    __tablename__ = "chat_message"

    room_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    sender_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)  # 人类发送者
    # 机器人发送的消息：sender_type=agent + sender_id=Agent.id
    sender_type: Mapped[str] = mapped_column(String(16), default="user")  # user/agent/system
    content: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(16), default="text")  # text/system
    # 附件（复用聊天附件结构：{type,file_key,name,mime,size,url}）
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # @提及的用户 id 列表
    mentions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 引用的消息 id（回复某条）
    reply_to_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0, index=True)  # 毫秒

    __table_args__ = (
        Index("ix_chat_msg_room_time", "room_id", "created_at"),
    )
