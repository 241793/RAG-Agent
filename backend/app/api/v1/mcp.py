"""MCP（Model Context Protocol）服务器管理接口。

- 管理 server（http/sse/stdio），敏感字段加密存、mask 回显。
- 测试连通性、同步工具清单（tools/list）、查看工具、手动试跑（tools/call）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import McpServer, User
from app.schemas.mcp import (
    McpCallIn,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
)
from app.services.audit_service import audited

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _to_out(s: McpServer) -> McpServerOut:
    return McpServerOut(
        id=s.id, name=s.name, transport=s.transport, url=s.url,
        command=s.command, args=s.args, env=s.env,
        headers={k: "••••" for k in (s.headers or {})} if s.headers else s.headers,
        auth_token_set=bool(s.auth_token),
        enabled=s.enabled, status=s.status, last_error=s.last_error,
        tools_count=len(s.tools_cache or []), last_synced_at=s.last_synced_at,
        timeout=s.timeout,
    )


def _encrypt_headers(headers: dict | None) -> dict | None:
    if not headers:
        return headers
    return {k: (v if isinstance(v, str) and v.startswith("enc:") else encrypt(str(v))) for k, v in headers.items()}


def _validate_transport(body) -> None:
    t = (body.transport or "http").lower()
    if t not in ("http", "sse", "stdio"):
        raise ValidationError("transport 只能为 http/sse/stdio")
    if t in ("http", "sse"):
        if not body.url:
            raise ValidationError("http/sse 型 MCP server 需要 url")
    else:
        from app.services.mcp_manager import check_stdio_allowed

        check_stdio_allowed(body.command or "")


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(
    user: User = Depends(require_permission("mcp:read")),
    db: AsyncSession = Depends(get_db),
) -> list[McpServerOut]:
    rows = (
        await db.execute(
            select(McpServer).where(McpServer.tenant_id == user.tenant_id).order_by(McpServer.id.desc())
        )
    ).scalars().all()
    return [_to_out(s) for s in rows]


@router.post("/servers", response_model=McpServerOut)
@audited("mcp.create", "mcp_server")
async def create_server(
    body: McpServerCreate,
    user: User = Depends(require_permission("mcp:manage")),
    db: AsyncSession = Depends(get_db),
) -> McpServerOut:
    _validate_transport(body)
    s = McpServer(
        tenant_id=user.tenant_id,
        name=body.name,
        transport=(body.transport or "http").lower(),
        url=body.url,
        command=body.command,
        args=body.args,
        env=body.env,
        headers=_encrypt_headers(body.headers),
        auth_token=encrypt(body.auth_token) if body.auth_token else None,
        timeout=body.timeout,
        enabled=body.enabled,
        status="active",
    )
    db.add(s)
    await db.flush()
    return _to_out(s)


@router.patch("/servers/{server_id}", response_model=McpServerOut)
@audited("mcp.update", "mcp_server", id_arg="server_id")
async def update_server(
    server_id: int,
    body: McpServerUpdate,
    user: User = Depends(require_permission("mcp:manage")),
    db: AsyncSession = Depends(get_db),
) -> McpServerOut:
    s = await db.get(McpServer, server_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("MCP server 不存在")
    data = body.model_dump(exclude_unset=True)
    # 校验 transport 相关字段
    if any(k in data for k in ("transport", "url", "command")):
        from types import SimpleNamespace

        merged = SimpleNamespace(
            transport=data.get("transport", s.transport),
            url=data.get("url", s.url),
            command=data.get("command", s.command),
        )
        _validate_transport(merged)
    for k, v in data.items():
        if k == "headers":
            setattr(s, k, _encrypt_headers(v))
        elif k == "auth_token":
            setattr(s, k, encrypt(v) if v else None)
        else:
            setattr(s, k, v)
    await db.flush()
    if s.transport == "stdio":
        from app.services.mcp_manager import mcp_manager

        await mcp_manager.stop(server_id)  # 配置变更后重启长驻进程
    return _to_out(s)


@router.delete("/servers/{server_id}")
@audited("mcp.delete", "mcp_server", id_arg="server_id")
async def delete_server(
    server_id: int,
    user: User = Depends(require_permission("mcp:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    s = await db.get(McpServer, server_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("MCP server 不存在")
    from app.services.mcp_manager import mcp_manager

    await mcp_manager.stop(server_id)
    await db.delete(s)
    await db.flush()
    return {"message": "已删除"}


@router.post("/servers/{server_id}/test")
async def test_server(
    server_id: int,
    user: User = Depends(require_permission("mcp:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    s = await db.get(McpServer, server_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("MCP server 不存在")
    from app.services.mcp_client import McpError, build_client

    t0 = time.time()
    try:
        client = await build_client(s, db=db)
        info = await client.initialize()
        tools = await client.list_tools()
        s.status = "active"
        s.last_error = None
        await db.flush()
        return {
            "ok": True,
            "server_info": (info or {}).get("serverInfo") or {},
            "tools_count": len(tools),
            "latency_ms": int((time.time() - t0) * 1000),
        }
    except (McpError, ValidationError) as e:
        s.status = "error"
        s.last_error = str(e)[:500]
        await db.flush()
        return {"ok": False, "message": str(e)[:300], "latency_ms": int((time.time() - t0) * 1000)}


@router.post("/servers/{server_id}/sync")
async def sync_server(
    server_id: int,
    user: User = Depends(require_permission("mcp:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """拉取 tools/list 并缓存。"""
    s = await db.get(McpServer, server_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("MCP server 不存在")
    from app.services.mcp_client import McpError, build_client

    try:
        client = await build_client(s, db=db)
        await client.initialize()
        tools = await client.list_tools()
    except (McpError, ValidationError) as e:
        s.status = "error"
        s.last_error = str(e)[:500]
        await db.flush()
        raise ValidationError(f"同步失败：{str(e)[:300]}")
    s.tools_cache = tools
    s.last_synced_at = int(time.time() * 1000)
    s.status = "active"
    s.last_error = None
    await db.flush()
    return {"ok": True, "tools_count": len(tools)}


@router.get("/servers/{server_id}/tools")
async def list_server_tools(
    server_id: int,
    user: User = Depends(require_permission("mcp:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    s = await db.get(McpServer, server_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("MCP server 不存在")
    return [
        {
            "name": t.get("name"),
            "description": t.get("description"),
            "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}},
        }
        for t in (s.tools_cache or []) if isinstance(t, dict)
    ]


@router.post("/servers/{server_id}/tools/{tool_name}/call")
async def call_server_tool(
    server_id: int,
    tool_name: str,
    body: McpCallIn,
    user: User = Depends(require_permission("mcp:invoke")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动试跑某个 MCP 工具。"""
    s = await db.get(McpServer, server_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("MCP server 不存在")
    from app.services.mcp_client import McpError, build_client, content_to_text

    try:
        client = await build_client(s, db=db)
        result = await client.call_tool(tool_name, body.args)
    except (McpError, ValidationError) as e:
        return {"ok": False, "content": str(e)[:1000], "is_error": True}
    is_err = bool(result.get("isError")) if isinstance(result, dict) else False
    return {"ok": not is_err, "content": content_to_text(result)[:20000], "is_error": is_err}
