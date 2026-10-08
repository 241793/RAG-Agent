"""文件产物：AI 生成或用户上传、可供下载的文件记录（不入知识库）。"""
from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Artifact(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "artifact"

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    source: Mapped[str] = mapped_column(String(16), default="generated")  # generated|upload
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ms; None=永不过期
