"""客服工单 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=512)
    content: str = ""
    priority: str = "normal"  # low/normal/high/urgent
    assignee_id: int | None = None
    conversation_id: int | None = None
    channel_id: int | None = None
    category: str | None = None
    tags: list | None = None


class TicketReply(BaseModel):
    content: str = Field(min_length=1)


class TicketUpdate(BaseModel):
    status: str | None = None  # open/pending/resolved/closed
    priority: str | None = None
    assignee_id: int | None = None
    resolution: str | None = None
    category: str | None = None
    tags: list | None = None
    watch: bool | None = None  # 有新回复是否通知客服


class TicketNote(BaseModel):
    content: str = Field(min_length=1)


class TicketBulkIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    action: str  # close|resolve|assign|priority|tag|reopen
    value: int | str | None = None


class TicketAssignIn(BaseModel):
    assignee_id: int | None = None


class QuickReplyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)
    category: str | None = None
    scope: str = "global"  # global|personal
    enabled: bool = True


class QuickReplyUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    scope: str | None = None
    enabled: bool | None = None


class QuickReplyOut(BaseModel):
    id: int
    title: str
    content: str
    category: str | None = None
    scope: str = "global"
    enabled: bool = True
    created_by: int | None = None

    model_config = {"from_attributes": True}


class TicketOut(BaseModel):
    id: int
    status: str
    priority: str
    subject: str
    category: str | None = None
    tags: list | None = None
    source: str = "channel"
    channel_id: int | None = None
    channel_kind: str | None = None
    external_user: str | None = None
    conversation_id: int | None = None
    assignee_id: int | None = None
    messages: list | None = None
    internal_notes: list | None = None
    last_message_at: int | None = None
    closed_at: int | None = None
    resolution: str | None = None
    first_response_at: int | None = None
    sla_due_at: int | None = None
    sla_breached: bool = False
    satisfaction: int | None = None
    satisfaction_comment: str | None = None
    customer_lang: str | None = None
    watch: bool = True

    model_config = {"from_attributes": True}
