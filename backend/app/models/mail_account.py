"""个人邮箱账号：用户配置自己的邮箱（IMAP 收 + SMTP 发），可选自动入库知识库。

与 EmailSource（租户级「邮箱→知识库」共享入库管道）不同：MailAccount 是**用户级**，
面向个人收发；密码经 core.crypto 加密，只读拉取（不标记已读）。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class MailAccount(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "mail_account"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)  # 归属用户
    label: Mapped[str] = mapped_column(String(128), default="")  # 显示名（如「工作邮箱」）
    email_addr: Mapped[str] = mapped_column(String(256), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 发信显示名

    # ---- IMAP（收）----
    imap_host: Mapped[str] = mapped_column(String(256), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    imap_username: Mapped[str] = mapped_column(String(256), nullable=False)
    imap_password: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 加密
    folder: Mapped[str] = mapped_column(String(128), default="INBOX")

    # ---- SMTP（发）----
    smtp_host: Mapped[str | None] = mapped_column(String(256), nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_use_ssl: Mapped[bool] = mapped_column(Boolean, default=False)
    smtp_starttls: Mapped[bool] = mapped_column(Boolean, default=True)
    smtp_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 加密

    # ---- 可选入库到知识库 ----
    auto_ingest: Mapped[bool] = mapped_column(Boolean, default=False)
    default_kb_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ingest_mode: Mapped[str] = mapped_column(String(16), default="both")  # both|attach|body
    allow_from: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subject_keywords: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auto_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tag_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ---- 增量游标与状态 ----
    uid_cursor: Mapped[int] = mapped_column(Integer, default=0)
    uid_validity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    seen_uids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_poll_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ms
    ingested_count: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|error
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
