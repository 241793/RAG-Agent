"""AI 工具级 RBAC 测试。

断言：
  - 员工（仅 chat:use）只能拿到 knowledge_retrieval 工具
  - http / 脚本 / 管理类工具对无权者不可见
  - tool_allowed 对未声明权限的工具默认拒绝
  - 部门级越权授予不生效（scope_id 不匹配用户部门）
"""
from __future__ import annotations

import asyncio

from app.agents.tools.builtin import HttpRequestTool, KnowledgeRetrievalTool
from app.agents.tools.registry import (
    registry,
    resolve_tools,
    tool_allowed,
)
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.middleware.auth_dep import get_user_permission_codes
from app.models import Department, Role, RolePermission, Permission, Tenant, User, UserRole


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        tenant = (
            await db.execute(__import__("sqlalchemy").select(Tenant).where(Tenant.slug == "tr1"))
        ).scalar_one_or_none()
        if tenant:
            emp = (
                await db.execute(__import__("sqlalchemy").select(User).where(User.username == "emp"))
            ).scalar_one()
            d1 = (
                await db.execute(__import__("sqlalchemy").select(Department).where(Department.name == "DX"))
            ).scalar_one()
            d2 = (
                await db.execute(__import__("sqlalchemy").select(Department).where(Department.name == "DY"))
            ).scalar_one()
            from app.services.permission_seed import seed_permissions_and_roles

            role_ids = await seed_permissions_and_roles(db)
            await db.commit()
            return {"tenant_id": tenant.id, "emp": emp.id, "d2": d2.id, "d1": d1.id, "role_ids": role_ids}

        tenant = Tenant(name="TR", slug="tr1")
        db.add(tenant)
        await db.flush()

        d1 = Department(tenant_id=tenant.id, name="DX", parent_id=None, path="", depth=0)
        d2 = Department(tenant_id=tenant.id, name="DY", parent_id=None, path="", depth=0)
        db.add_all([d1, d2])
        await db.flush()
        d1.path = f"{d1.id}."
        d2.path = f"{d2.id}."

        emp = User(
            tenant_id=tenant.id, username="emp", password_hash=hash_password("x"),
            department_id=d2.id, display_name="员工",
        )
        db.add(emp)
        await db.flush()

        # 播种内置权限/角色
        from app.services.permission_seed import seed_permissions_and_roles

        role_ids = await seed_permissions_and_roles(db)
        await db.commit()
        return {"tenant_id": tenant.id, "emp": emp.id, "d2": d2.id, "d1": d1.id, "role_ids": role_ids}


async def _grant_viewer(db, tenant_id, user_id, role_ids):
    from sqlalchemy import delete as _del

    await db.execute(_del(UserRole).where(UserRole.user_id == user_id))
    db.add(UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role_ids["viewer"], scope_type="tenant", scope_id=0))
    await db.commit()


def test_tool_permission_attributes():
    assert KnowledgeRetrievalTool.required_permission == "chat:use"
    assert HttpRequestTool.required_permission == "tool:invoke"
    assert KnowledgeRetrievalTool.kind == "read"
    assert HttpRequestTool.kind == "write"


def test_tool_allowed_matrix():
    assert tool_allowed(KnowledgeRetrievalTool(), {"chat:use"}) is True
    assert tool_allowed(HttpRequestTool(), {"chat:use"}) is False
    assert tool_allowed(HttpRequestTool(), {"tool:invoke"}) is True
    assert tool_allowed(HttpRequestTool(), {"*"}) is True

    class _Undeclared:
        name = "mystery"
        description = ""
        parameters = {}

    # 未声明权限的工具默认不暴露（白名单）
    assert tool_allowed(_Undeclared(), {"chat:use"}) is False
    assert tool_allowed(_Undeclared(), {"*"}) is True


async def _run():
    d = await _setup()
    async with AsyncSessionLocal() as db:
        await _grant_viewer(db, d["tenant_id"], d["emp"], d["role_ids"])

    # 1) 员工权限码 = viewer（含 chat:use，不含 tool:invoke/skill:execute）
    async with AsyncSessionLocal() as db:
        emp = await db.get(User, d["emp"])
        perms = await get_user_permission_codes(db, emp)
    assert "chat:use" in perms, perms
    assert "tool:invoke" not in perms
    assert "skill:execute" not in perms

    # 2) 员工 resolve_tools：只应拿到 knowledge_retrieval
    async with AsyncSessionLocal() as db:
        tools = await resolve_tools(
            db,
            tool_config={"builtin": {"knowledge_retrieval": {"enabled": True}, "http_request": {"enabled": True}}},
            skill_ids=None,
            tenant_id=d["tenant_id"],
            perms=perms,
        )
    names = [t.name for t in tools]
    assert names == ["knowledge_retrieval"], names

    # 3) admin（*）resolve_tools：拿到两个内置工具
    async with AsyncSessionLocal() as db:
        tools2 = await resolve_tools(
            db,
            tool_config={"builtin": {"knowledge_retrieval": {"enabled": True}, "http_request": {"enabled": True}}},
            skill_ids=None,
            tenant_id=d["tenant_id"],
            perms={"*"},
        )
    names2 = sorted(t.name for t in tools2)
    assert names2 == ["http_request", "knowledge_retrieval"], names2

    # 4) 管理类工具：默认不暴露（未启用 admin）
    async with AsyncSessionLocal() as db:
        tools3 = await resolve_tools(
            db,
            tool_config={"builtin": {"knowledge_retrieval": {"enabled": True}}},
            skill_ids=None,
            tenant_id=d["tenant_id"],
            perms={"*"},
        )
    assert all(t.name not in ("create_skill", "list_skills") for t in tools3)

    # 5) 启用 admin 工具 + admin 权限 → 出现管理类工具
    async with AsyncSessionLocal() as db:
        tools4 = await resolve_tools(
            db,
            tool_config={"builtin": {"knowledge_retrieval": {"enabled": True}}, "admin": {"enabled": True}},
            skill_ids=None,
            tenant_id=d["tenant_id"],
            perms={"*"},
        )
    names4 = {t.name for t in tools4}
    assert "list_skills" in names4 and "create_skill" in names4, names4

    # 6) 员工即使 agent 启用了 admin 工具，也拿不到**写类**管理工具（无 skill:edit/agent:edit）
    async with AsyncSessionLocal() as db:
        tools5 = await resolve_tools(
            db,
            tool_config={"admin": {"enabled": True}},
            skill_ids=None,
            tenant_id=d["tenant_id"],
            perms=perms,
        )
    names5 = {t.name for t in tools5}
    assert "create_skill" not in names5, names5
    assert "write_skill_file" not in names5, names5
    assert "create_agent" not in names5, names5
    # viewer 有 kb:read/doc:read，只读类管理工具中与 kb/doc 相关的可用（最小权限）
    assert "list_kbs" in names5, names5

    print("OK tool_rbac")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_tool_rbac():
    _run_async(_run())


async def _dept_scope_violation():
    """部门级角色：授予到非用户所属部门时不应生效。"""
    d = await _setup()
    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete as _del

        # 清理该用户既有授予，避免重复运行累积
        await db.execute(_del(UserRole).where(UserRole.user_id == d["emp"]))
        # 自建一个部门级测试角色（内置部门级角色已下线，此处独立构造以验证范围隔离逻辑）
        role = (
            await db.execute(__import__("sqlalchemy").select(Role).where(
                Role.code == "test_dept_role", Role.tenant_id.is_(None)))
        ).scalar_one_or_none()
        if not role:
            role = Role(tenant_id=None, code="test_dept_role", name="测试部门角色",
                        scope="department", is_system=False)
            db.add(role)
            await db.flush()
        # 给测试角色挂一个可区分的权限（kb:create），用于验证「生效/不生效」
        from app.models import Permission as _Perm, RolePermission as _RP
        perm = (await db.execute(__import__("sqlalchemy").select(_Perm).where(
            _Perm.code == "kb:create"))).scalar_one_or_none()
        if perm:
            linked = (await db.execute(__import__("sqlalchemy").select(_RP).where(
                _RP.role_id == role.id, _RP.permission_id == perm.id))).scalar_one_or_none()
            if not linked:
                db.add(_RP(role_id=role.id, permission_id=perm.id))
                await db.flush()
        db.add(UserRole(
            tenant_id=d["tenant_id"], user_id=d["emp"], role_id=role.id,
            scope_type="department", scope_id=d["d1"],  # 非用户所属部门
        ))
        await db.commit()

    async with AsyncSessionLocal() as db:
        emp = await db.get(User, d["emp"])
        perms = await get_user_permission_codes(db, emp)
    # 越权授予不生效：不应含 dept_editor 的 kb:create
    assert "kb:create" not in perms, perms

    # 改成授予到 emp 所属部门 d2 → 生效
    async with AsyncSessionLocal() as db:
        ur = (await db.execute(
            __import__("sqlalchemy").select(UserRole).where(UserRole.user_id == d["emp"])
        )).scalars().first()
        ur.scope_id = d["d2"]
        await db.commit()
    async with AsyncSessionLocal() as db:
        emp = await db.get(User, d["emp"])
        perms2 = await get_user_permission_codes(db, emp)
    assert "kb:create" in perms2, perms2
    print("OK dept_scope")


def test_dept_scope_violation_blocked():
    _run_async(_dept_scope_violation())
