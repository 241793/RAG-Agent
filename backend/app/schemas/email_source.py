"""邮件入库源 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class EmailSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source_account_id: int | None = None  # 引用个人邮箱账号（复用其 IMAP 凭证）
    imap_host: str = ""
    imap_port: int = 993
    use_ssl: bool = True
    username: str = ""
    password: str | None = None
    folder: str = "INBOX"
    kb_id: int
    ingest_mode: str = "both"  # both|attach|body
    allow_from: str | None = None
    subject_keywords: str | None = None
    auto_tags: list[str] | None = None              # 固定附加标签
    tag_rules: dict[str, list[str]] | None = None   # {关键词: [标签]}
    enabled: bool = True


class EmailSourceUpdate(BaseModel):
    name: str | None = None
    source_account_id: int | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    use_ssl: bool | None = None
    username: str | None = None
    password: str | None = None
    folder: str | None = None
    kb_id: int | None = None
    ingest_mode: str | None = None
    allow_from: str | None = None
    subject_keywords: str | None = None
    auto_tags: list[str] | None = None
    tag_rules: dict[str, list[str]] | None = None
    enabled: bool | None = None


class EmailSourceOut(BaseModel):
    id: int
    name: str
    source_account_id: int | None = None
    imap_host: str
    imap_port: int
    use_ssl: bool
    username: str
    password_set: bool = False
    folder: str
    kb_id: int
    ingest_mode: str
    allow_from: str | None = None
    subject_keywords: str | None = None
    auto_tags: list[str] | None = None
    tag_rules: dict[str, list[str]] | None = None
    uid_cursor: int = 0
    enabled: bool
    status: str
    last_error: str | None = None
    last_sync_at: int | None = None
    ingested_count: int = 0

    model_config = {"from_attributes": True}
