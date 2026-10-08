"""外部 IM 渠道配置（QQ机器人/微信/企业微信/飞书）。密钥经 core.crypto 加密。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Channel(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "channel"

    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # qqbot/wxclaw/wework/feishu
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 含加密后的密钥
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 外部用户落地的默认租户（不填则用渠道所属租户）
    default_tenant_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)   # 渠道默认知识库
    # 检索范围：auto=按用户权限自动 / custom=仅指定库 / off=不检索（纯聊天）
    kb_mode: Mapped[str] = mapped_column(String(8), default="auto")
    # 服务模式：qa=只答（不转人工）/ support=客服（识别转人工关键词并建单）
    service_mode: Mapped[str] = mapped_column(String(8), default="qa")
    # 默认语言（多语言客服：zh/en/ja/... 空=自动判断）
    default_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_agent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 默认智能体
    reply_mode: Mapped[str] = mapped_column(String(16), default="rag")  # rag/agent
    command_prefix: Mapped[str] = mapped_column(String(8), default="/")
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/deleted
    # 运行时状态（UI 展示）
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
