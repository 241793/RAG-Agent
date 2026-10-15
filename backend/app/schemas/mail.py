"""个人邮件 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MailAccountIn(BaseModel):
    label: str = ""
    email_addr: str
    from_name: str | None = None
    # IMAP
    imap_host: str
    imap_port: int = 993
    imap_use_ssl: bool = True
    imap_username: str
    imap_password: str | None = None  # 留空=不变（更新时）
    folder: str = "INBOX"
    # SMTP
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_use_ssl: bool = False
    smtp_starttls: bool = True
    smtp_username: str | None = None
    smtp_password: str | None = None
    # 可选入库
    auto_ingest: bool = False
    default_kb_id: int | None = None
    allow_from: str | None = None
    subject_keywords: str | None = None
    auto_tags: list[str] | None = None
    tag_rules: dict[str, list[str]] | None = None
    enabled: bool = True


class MailAccountOut(BaseModel):
    id: int
    label: str
    email_addr: str
    from_name: str | None = None
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    imap_username: str
    imap_password_set: bool = False
    folder: str
    smtp_host: str | None = None
    smtp_port: int
    smtp_use_ssl: bool
    smtp_starttls: bool
    smtp_username: str | None = None
    smtp_password_set: bool = False
    auto_ingest: bool
    default_kb_id: int | None = None
    allow_from: str | None = None
    subject_keywords: str | None = None
    auto_tags: list[str] | None = None
    last_poll_at: int | None = None
    ingested_count: int = 0
    enabled: bool
    status: str
    last_error: str | None = None

    model_config = {"from_attributes": True}


class MailMessageOut(BaseModel):
    id: int
    account_id: int
    folder: str
    subject: str
    from_addr: str
    from_name: str | None = None
    to_addrs: list | None = None
    date: int | None = None
    snippet: str | None = None
    seen: bool
    answered: bool
    starred: bool
    has_attachments: bool
    document_id: int | None = None

    model_config = {"from_attributes": True}


class MailMessageDetail(MailMessageOut):
    body_text: str | None = None
    body_html: str | None = None
    cc_addrs: list | None = None
    attachments: list | None = None
    in_reply_to: str | None = None


class MailSendIn(BaseModel):
    account_id: int
    to: list[str] = Field(min_length=1)
    cc: list[str] = []
    subject: str = ""
    body_text: str = ""
    body_html: str | None = None
    reply_to_id: int | None = None  # 回复某封（取 in_reply_to）
