"""请求上下文中间件：request_id 与租户上下文（contextvar）。"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_ctx: ContextVar[int] = ContextVar("tenant_id", default=0)
user_id_ctx: ContextVar[int] = ContextVar("user_id", default=0)
# 审计用：发起请求的客户端信息
ip_ctx: ContextVar[str] = ContextVar("ip", default="")
user_agent_ctx: ContextVar[str] = ContextVar("user_agent", default="")
# 审计用：当前主体类型（user/apikey）与展示名
actor_type_ctx: ContextVar[str] = ContextVar("actor_type", default="user")
actor_name_ctx: ContextVar[str] = ContextVar("actor_name", default="")
# 审计用：本次请求积累的审计记录（在请求内收集，响应后统一落库）
audit_buffer_ctx: ContextVar[list] = ContextVar("audit_buffer", default=[])


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request_id_ctx.set(rid)
        # 客户端 IP：优先取 X-Forwarded-For 首段
        fwd = request.headers.get("X-Forwarded-For")
        client_ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
        ip_ctx.set(client_ip)
        user_agent_ctx.set(request.headers.get("User-Agent", "")[:256])
        audit_buffer_ctx.set([])
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
