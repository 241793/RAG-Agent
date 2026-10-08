"""MCP 服务器 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport: str = "http"  # http | sse | stdio
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    headers: dict | None = None
    auth_token: str | None = None
    timeout: int | None = None
    enabled: bool = True


class McpServerUpdate(BaseModel):
    name: str | None = None
    transport: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    headers: dict | None = None
    auth_token: str | None = None
    timeout: int | None = None
    enabled: bool | None = None


class McpServerOut(BaseModel):
    id: int
    name: str
    transport: str
    url: str | None = None
    command: str | None = None
    args: list | None = None
    env: dict | None = None
    headers: dict | None = None
    auth_token_set: bool = False
    enabled: bool
    status: str
    last_error: str | None = None
    tools_count: int = 0
    last_synced_at: int | None = None
    timeout: int | None = None

    model_config = {"from_attributes": True}


class McpCallIn(BaseModel):
    args: dict = Field(default_factory=dict)
