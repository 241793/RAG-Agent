"""检索未命中日志：记录查不到结果的 query，供知识库运营（补内容 / 优化）。"""
from __future__ import annotations

from sqlalchemy import BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class RetrievalMiss(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "retrieval_miss"

    query: Mapped[str] = mapped_column(Text, nullable=False)
    kb_ids: Mapped[list | None] = mapped_column(String(256), nullable=True)  # 逗号分隔的 kb id（字符串存）
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="chat")  # chat | channel | retrieval_debug
