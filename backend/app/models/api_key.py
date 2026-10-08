"""API Key 模型：供内部系统调用本平台接口。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class ApiKey(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "api_key"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)  # 展示用，如 sk-rag-ab12
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)  # sha256(明文)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 归属用户（虚拟主体）
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["chat:use","retrieval:query"] 或 ["*"]
    kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 可选：限制可访问知识库
    rate_limit: Mapped[int] = mapped_column(Integer, default=60)  # 每分钟上限
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/revoked
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
