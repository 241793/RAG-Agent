"""会话与消息。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Conversation(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "conversation"

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    app_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 本会话绑定的知识库
    model_config_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 多轮压缩摘要
    summary_upto_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 已摘要到的消息 id（水位）
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(SmallInteger, default=0)


class Message(Base, IdMixin, TenantMixin):
    __tablename__ = "message"

    conversation_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user/assistant/system/tool
    content: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(16), default="text")
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{type,file_key,url,mime,size,name}]
    artifacts: Mapped[list | None] = mapped_column(JSON, nullable=True)  # AI 产物 [{name,file_key,artifact_id,url,mime,size}]
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)  # 由应用写入毫秒时间戳
