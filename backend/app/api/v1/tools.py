"""工具接口：内置工具（只读）+ 自定义 HTTP 工具 CRUD + 试跑。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.registry import registry
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import get_principal_set, require_permission
from app.services.audit_service import audited
from app.models import Tool, User
from app.schemas.agent import ToolCreate, ToolOut, ToolTestRequest
from app.services.permission import PrincipalSet

router = APIRouter(prefix="/tools", tags=["tool"])


@router.get("", response_model=list[ToolOut])
async def list_tools(
    user: User = Depends(require_permission("tool:read")),
    db: AsyncSession = Depends(get_db),
) -> list[ToolOut]:
    out: list[ToolOut] = []
    # 内置工具（代码注册，只读）
    for t in registry.all_builtin():
        out.append(
            ToolOut(
                id=0,
                name=t.name,
                display_name=t.name,
                description=t.description,
                kind="builtin",
                parameters=t.parameters,
                source=None,
                enabled=True,
                status="active",
                builtin=True,
            )
        )
    # 自定义工具
    rows = (
        await db.execute(
            select(Tool).where(Tool.tenant_id == user.tenant_id).order_by(Tool.id.desc())
        )
    ).scalars().all()
    for t in rows:
        out.append(
            ToolOut(
                id=t.id,
                name=t.name,
                display_name=t.display_name or t.name,
                description=t.description,
                kind=t.kind,
                parameters=t.parameters,
                source=t.source,
                enabled=t.enabled,
                status=t.status,
                builtin=False,
            )
        )
    return out


@router.get("/admin-list")
async def list_admin_tools(
    user: User = Depends(require_permission("tool:read")),
) -> list[dict]:
    """全部管理类工具的清单（name/description/权限），供智能体编辑页选择启用哪些。"""
    return [
        {"name": t.name, "description": t.description, "permission": t.required_permission, "kind": t.kind}
        for t in sorted(registry.all_admin(), key=lambda x: x.name)
    ]


@router.post("", response_model=ToolOut)
@audited("tool.create", "tool")
async def create_tool(
    body: ToolCreate,
    user: User = Depends(require_permission("tool:manage")),
    db: AsyncSession = Depends(get_db),
) -> ToolOut:
    t = Tool(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        name=body.name,
        display_name=body.display_name or body.name,
        description=body.description,
        kind="http",
        parameters=body.parameters,
        source=body.source,
    )
    db.add(t)
    await db.flush()
    return ToolOut(
        id=t.id,
        name=t.name,
        display_name=t.display_name,
        description=t.description,
        kind=t.kind,
        parameters=t.parameters,
        source=t.source,
        enabled=t.enabled,
        status=t.status,
        builtin=False,
    )


@router.delete("/{tool_id}")
@audited("tool.delete", "tool", id_arg="tool_id")
async def delete_tool(
    tool_id: int,
    user: User = Depends(require_permission("tool:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await db.get(Tool, tool_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工具不存在")
    await db.delete(t)
    await db.flush()
    return {"message": "已删除"}


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: int,
    body: ToolTestRequest,
    user: User = Depends(require_permission("tool:manage")),
    ps: PrincipalSet = Depends(get_principal_set),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.agents.tools.base import ToolContext
    from app.agents.tools.builtin import HttpRequestTool

    t = await db.get(Tool, tool_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工具不存在")

    # 用通用 HTTP 工具以 source 配置试跑
    src = t.source or {}
    http = src.get("http") or {}
    tool = HttpRequestTool()
    ctx = ToolContext(
        db=db,
        ps=ps,
        tenant_id=user.tenant_id,
        user_id=user.id,
        config={"allow_hosts": http.get("allow_hosts"), "timeout": http.get("timeout", 20)},
    )
    result = await tool.run(body.args, ctx)
    return {"ok": not result.is_error, "content": result.content[:2000], "is_error": result.is_error}
