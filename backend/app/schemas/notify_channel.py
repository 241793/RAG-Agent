"""通知渠道 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class NotifyChannelCreate(BaseModel):
    kind: str = "webhook"  # inapp | webhook | wecom | dingtalk | smtp | external
    name: str = Field(min_length=1, max_length=128)
    config: dict | None = None
    enabled: bool = True
    events: str | None = None  # 逗号分隔的订阅事件（空=全部）


class NotifyChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    events: str | None = None


class NotifyChannelOut(BaseModel):
    id: int
    kind: str
    name: str
    config: dict | None = None
    enabled: bool
    events: str | None = None

    model_config = {"from_attributes": True}
