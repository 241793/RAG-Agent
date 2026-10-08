"""事件订阅 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class EventSubCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1)
    events: str | None = None  # 逗号分隔；空=全部
    secret: str | None = None  # HMAC 密钥
    enabled: bool = True


class EventSubUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    events: str | None = None
    secret: str | None = None
    enabled: bool | None = None


class EventSubOut(BaseModel):
    id: int
    name: str
    url: str
    events: str | None = None
    secret_set: bool = False
    enabled: bool

    model_config = {"from_attributes": True}
