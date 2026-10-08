"""MCP（Model Context Protocol）服务器配置。

支持三种传输：
- http  ：streamable-http（POST JSON-RPC）
- sse   ：Server-Sent Events（GET 建流拿 endpoint，POST 发请求）
- stdio ：本地子进程（长驻，需 settings.mcp_allow_stdio 且命令在白名单）

敏感字段（headers 中的值、auth_token）加密存储。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class McpServer(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "mcp_server"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport: Mapped[str] = mapped_column(String(8), default="http")  # http | sse | stdio
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # http/sse base_url
    command: Mapped[str | None] = mapped_column(String(512), nullable=True)  # stdio 命令
    args: Mapped[list | None] = mapped_column(JSON, nullable=True)  # stdio 命令参数
    env: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # stdio 环境变量（值可含密钥）
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # http/sse 附加请求头（值加密）
    auth_token: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # Bearer（加密）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | error | disabled
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_cache: Mapped[list | None] = mapped_column(JSON, nullable=True)  # tools/list 结果缓存
    last_synced_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ms
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
