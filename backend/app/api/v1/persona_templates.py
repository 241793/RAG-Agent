"""人设模板接口：可复用 system_prompt 素材的 CRUD（管理员维护）。

权限复用 agent:read / agent:edit（已授予 app_admin / agent_admin），
不新增权限码 —— 新增的码不会自动授予存量自定义角色，反而更麻烦。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import ConflictError, NotFoundError
from app.middleware.auth_dep import require_permission
from app.models import AgentPersonaTemplate, User
from app.schemas.agent import (
    PersonaTemplateCreate,
    PersonaTemplateOut,
    PersonaTemplateUpdate,
)
from app.services.audit_service import audited

router = APIRouter(prefix="/persona-templates", tags=["agent"])


async def _get(db: AsyncSession, tid: int, user_tenant: int) -> AgentPersonaTemplate:
    t = await db.get(AgentPersonaTemplate, tid)
    if not t or t.tenant_id != user_tenant:
        raise NotFoundError("模板不存在")
    return t


@router.get("", response_model=list[PersonaTemplateOut])
async def list_templates(
    category: str | None = None,
    enabled: bool | None = None,
    user: User = Depends(require_permission("agent:read")),
    db: AsyncSession = Depends(get_db),
) -> list[AgentPersonaTemplate]:
    stmt = select(AgentPersonaTemplate).where(
        AgentPersonaTemplate.tenant_id == user.tenant_id
    )
    if category:
        stmt = stmt.where(AgentPersonaTemplate.category == category)
    if enabled is not None:
        stmt = stmt.where(AgentPersonaTemplate.enabled.is_(enabled))
    # 内置优先，其次按 sort，最后按 id
    stmt = stmt.order_by(
        AgentPersonaTemplate.is_builtin.desc(),
        AgentPersonaTemplate.sort,
        AgentPersonaTemplate.id,
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=PersonaTemplateOut)
@audited("persona_template.create", "persona_template")
async def create_template(
    body: PersonaTemplateCreate,
    user: User = Depends(require_permission("agent:edit")),
    db: AsyncSession = Depends(get_db),
) -> AgentPersonaTemplate:
    t = AgentPersonaTemplate(
        tenant_id=user.tenant_id,
        created_by=user.id,
        is_builtin=False,  # 只允许播种产生内置模板，接口创建的永远是自定义
        **body.model_dump(),
    )
    db.add(t)
    await db.flush()
    return t


@router.patch("/{template_id}", response_model=PersonaTemplateOut)
@audited("persona_template.update", "persona_template", id_arg="template_id")
async def update_template(
    template_id: int,
    body: PersonaTemplateUpdate,
    user: User = Depends(require_permission("agent:edit")),
    db: AsyncSession = Depends(get_db),
) -> AgentPersonaTemplate:
    """内置模板**允许编辑**（管理员可调成自家风格），但不允许删除。"""
    t = await _get(db, template_id, user.tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    await db.flush()
    return t


@router.delete("/{template_id}")
@audited("persona_template.delete", "persona_template", id_arg="template_id")
async def delete_template(
    template_id: int,
    user: User = Depends(require_permission("agent:edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await _get(db, template_id, user.tenant_id)
    if t.is_builtin:
        raise ConflictError("内置模板不可删除；如需保留原版再修改，请使用「复制」")
    await db.delete(t)
    await db.flush()
    return {"message": "已删除"}


@router.post("/{template_id}/clone", response_model=PersonaTemplateOut)
@audited("persona_template.clone", "persona_template", id_arg="template_id")
async def clone_template(
    template_id: int,
    user: User = Depends(require_permission("agent:edit")),
    db: AsyncSession = Depends(get_db),
) -> AgentPersonaTemplate:
    """复制为新模板（自定义），便于在保留内置原版的前提下修改。"""
    src = await _get(db, template_id, user.tenant_id)
    t = AgentPersonaTemplate(
        tenant_id=user.tenant_id,
        created_by=user.id,
        name=f"{src.name}（副本）",
        slug=None,  # 副本不参与内置播种去重
        description=src.description,
        system_prompt=src.system_prompt,
        category=src.category,
        icon=src.icon,
        tags=list(src.tags or []),
        sort=src.sort,
        enabled=True,
        is_builtin=False,
    )
    db.add(t)
    await db.flush()
    return t
