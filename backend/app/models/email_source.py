"""邮件入库源：从 IMAP 邮箱拉取邮件，正文与附件入库到指定知识库。

使用：管理员配置一个邮箱（IMAP 主机/账号/密码 + 目标知识库），定时轮询拉取新邮件，
正文 + 附件（docx/xlsx/pdf 等）落库为 Document 并走正常入库流水线。

安全：密码经 core.crypto 加密存储；只读拉取（不删除、不标记已读，避免影响用户邮箱）。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class EmailSource(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "email_source"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    imap_host: Mapped[str] = mapped_column(String(256), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    password: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 加密
    folder: Mapped[str] = mapped_column(String(128), default="INBOX")  # 监听的邮箱文件夹
    kb_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)  # 目标知识库
    # 仅入库附件 / 正文也入库 / 两者
    ingest_mode: Mapped[str] = mapped_column(String(16), default="both")  # both|attach|body
    # 只拉取该发件人（逗号分隔，空=不限）
    allow_from: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # 主题关键词过滤（逗号分隔，空=不限）
    subject_keywords: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 归属用户
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|error|disabled
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 已处理的邮件 UID（去重），JSON 存最近 N 个
    seen_uids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_sync_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ms
    ingested_count: Mapped[int] = mapped_column(Integer, default=0)
