"""邮件消息（收件箱持久化）：收到的邮件 / 发件记录落库，支持已读/星标/删除。

与「邮件入库」的区别：MailMessage 保留邮件**原文**（正文/HTML/收件人/附件元数据），
是个人邮件管理的核心；附件二进制存 storage，DB 只存元数据避免库膨胀。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class MailMessage(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "mail_message"
    __table_args__ = (
        # 同账号同文件夹同 UID 唯一（防重复拉取）；发件记录 uid 为空不参与
        Index("uq_mail_msg_account_folder_uid", "account_id", "folder", "uid", unique=True),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    folder: Mapped[str] = mapped_column(String(16), default="INBOX")  # INBOX|Sent|Drafts|Trash
    uid: Mapped[str | None] = mapped_column(String(64), nullable=True)  # IMAP UID（发件为空）
    message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)  # RFC Message-ID

    subject: Mapped[str] = mapped_column(Text, default="")
    from_addr: Mapped[str] = mapped_column(String(512), default="")
    from_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    to_addrs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cc_addrs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    date: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ms

    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 列表摘要

    seen: Mapped[bool] = mapped_column(Boolean, default=False)
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)

    in_reply_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    references: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{filename, content_type, size, storage_path}]
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)

    document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 入库后回填
