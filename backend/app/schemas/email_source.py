"""邮件入库源 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class EmailSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    imap_host: str
    imap_port: int = 993
    use_ssl: bool = True
    username: str
    password: str | None = None
    folder: str = "INBOX"
    kb_id: int
    ingest_mode: str = "both"  # both|attach|body
    allow_from: str | None = None
    subject_keywords: str | None = None
    enabled: bool = True


class EmailSourceUpdate(BaseModel):
    name: str | None = None
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
    enabled: bool | None = None


class EmailSourceOut(BaseModel):
    id: int
    name: str
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
    enabled: bool
    status: str
    last_error: str | None = None
    last_sync_at: int | None = None
    ingested_count: int = 0

    model_config = {"from_attributes": True}
