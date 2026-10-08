"""非管理员权限完善测试：文档读取 KB 成员校验、部门/角色/组编辑授权、
新用户自动授 viewer、有效级别 _effective_perm、账号接口。

不依赖 HTTP 层，直接调用服务函数 + DB 组合验证。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.errors import PermissionDeniedError
from app.core.security import hash_password
from app.models import KBMember, KnowledgeBase, Role, Tenant, User, UserRole
from app.services.permission import (
    PrincipalSet,
    dept_principal,
    role_principal,
    user_principal,
)


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        # 幂等：整个测试会话共享一个测试库，重复调用复用同一租户/数据
        existing = (await db.execute(select(Tenant).where(Tenant.slug == "na_perm"))).scalar_one_or_none()
        if existing:
            kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == existing.id))).scalars().first()
            owner = (await db.execute(select(User).where(User.username == "na_owner"))).scalar_one()
            outsider = (await db.execute(select(User).where(User.username == "na_outsider"))).scalar_one()
            member_u = (await db.execute(select(User).where(User.username == "na_member"))).scalar_one()
            from app.models import Department

            dept = (await db.execute(select(Department).where(Department.name == "研发部"))).scalar_one()
            from app.services.permission_seed import seed_permissions_and_roles

            role_ids = await seed_permissions_and_roles(db)
            await db.commit()
            return {
                "tenant_id": existing.id, "dept_id": dept.id, "kb_id": kb.id,
                "owner": owner.id, "outsider": outsider.id, "member_u": member_u.id,
                "role_ids": role_ids,
            }

        tenant = Tenant(name="NA", slug="na_perm")
        db.add(tenant)
        await db.flush()

        from app.models import Department

        d1 = Department(tenant_id=tenant.id, name="研发部", parent_id=None, path="", depth=0)
        db.add(d1)
        await db.flush()
        d1.path = f"{d1.id}."

        owner = User(tenant_id=tenant.id, username="na_owner", password_hash=hash_password("x"), display_name="库主")
        outsider = User(tenant_id=tenant.id, username="na_outsider", password_hash=hash_password("x"), display_name="外部人")
        member_u = User(tenant_id=tenant.id, username="na_member", password_hash=hash_password("x"), display_name="成员", department_id=d1.id)
        db.add_all([owner, outsider, member_u])
        await db.flush()

        from app.services.permission_seed import seed_permissions_and_roles

        role_ids = await seed_permissions_and_roles(db)
        await db.commit()

        kb = KnowledgeBase(
            tenant_id=tenant.id, name="私库", visibility="private",
            embedding_dim=64, owner_id=owner.id,
        )
        db.add(kb)
        await db.flush()
        await db.commit()

        return {
            "tenant_id": tenant.id, "dept_id": d1.id, "kb_id": kb.id,
            "owner": owner.id, "outsider": outsider.id, "member_u": member_u.id,
            "role_ids": role_ids,
        }


async def _read_outsider_blocked():
    d = await _setup()
    from app.api.v1.document import _ensure_read

    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["outsider"])
        kb = await db.get(KnowledgeBase, d["kb_id"])
        try:
            await _ensure_read(db, user, kb)
            raise AssertionError("非成员读私有库应被拒绝")
        except PermissionDeniedError:
            pass
    print("OK read_outsider_blocked")


async def _upsert_member(db, tenant_id, kb_id, principal_id, perm_level):
    """幂等写入成员（测试共享同一库，重复 principal 不报唯一约束）。"""
    exist = (
        await db.execute(
            select(KBMember).where(KBMember.kb_id == kb_id, KBMember.principal_id == principal_id)
        )
    ).scalar_one_or_none()
    if exist:
        exist.perm_level = perm_level
    else:
        db.add(KBMember(
            tenant_id=tenant_id, kb_id=kb_id,
            principal_id=principal_id, perm_level=perm_level,
        ))


async def _read_readmember_ok():
    d = await _setup()
    from app.api.v1.document import _ensure_read

    async with AsyncSessionLocal() as db:
        await _upsert_member(db, d["tenant_id"], d["kb_id"], user_principal(d["member_u"]), "viewer")
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["member_u"])
        kb = await db.get(KnowledgeBase, d["kb_id"])
        await _ensure_read(db, user, kb)  # 不抛即通过
    print("OK read_member_ok")


async def _edit_by_department_principal():
    """部门被授 editor → 部门成员可编辑（此前只认 user principal，会漏）。"""
    d = await _setup()
    from app.api.v1.document import _ensure_edit

    async with AsyncSessionLocal() as db:
        await _upsert_member(db, d["tenant_id"], d["kb_id"], dept_principal(d["dept_id"]), "editor")
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["member_u"])  # 属于 d1
        kb = await db.get(KnowledgeBase, d["kb_id"])
        await _ensure_edit(db, user, kb)
    print("OK edit_by_dept")


async def _edit_by_role_principal():
    d = await _setup()
    from app.api.v1.document import _ensure_edit

    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.tenant_id.is_(None), Role.code == "kb_editor"))).scalar_one()
        exist = (
            await db.execute(select(UserRole).where(UserRole.user_id == d["member_u"], UserRole.role_id == role.id))
        ).scalar_one_or_none()
        if not exist:
            db.add(UserRole(
                tenant_id=d["tenant_id"], user_id=d["member_u"], role_id=role.id,
                scope_type="tenant", scope_id=0,
            ))
        await _upsert_member(db, d["tenant_id"], d["kb_id"], role_principal(role.id), "editor")
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["member_u"])
        kb = await db.get(KnowledgeBase, d["kb_id"])
        await _ensure_edit(db, user, kb)
    print("OK edit_by_role")


async def _effective_perm_levels():
    d = await _setup()
    from app.api.v1.kb import _effective_perm

    async with AsyncSessionLocal() as db:
        owner = await db.get(User, d["owner"])
        kb = await db.get(KnowledgeBase, d["kb_id"])
        ps = await __import__("app.middleware.auth_dep", fromlist=["load_principal_set"]).load_principal_set(db, owner)
        assert await _effective_perm(db, ps, kb) == "owner"

    # 成员 editor
    async with AsyncSessionLocal() as db:
        await _upsert_member(db, d["tenant_id"], d["kb_id"], user_principal(d["member_u"]), "editor")
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["member_u"])
        kb = await db.get(KnowledgeBase, d["kb_id"])
        from app.middleware.auth_dep import load_principal_set
        ps = await load_principal_set(db, user)
        assert await _effective_perm(db, ps, kb) == "editor"

    # 非成员 → viewer（公开/内部只读语义兜底）
    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["outsider"])
        kb = await db.get(KnowledgeBase, d["kb_id"])
        from app.middleware.auth_dep import load_principal_set
        ps = await load_principal_set(db, user)
        assert await _effective_perm(db, ps, kb) == "viewer"
    print("OK effective_perm")


async def _create_user_grants_viewer():
    """新用户创建后权限集应含 viewer（不再空集 403）。"""
    d = await _setup()
    from app.api.v1.rbac import create_user
    from app.middleware.auth_dep import get_user_permission_codes
    from app.schemas.rbac import UserCreate

    async with AsyncSessionLocal() as db:
        admin = await db.get(User, d["owner"])
        admin.is_admin = True
        await db.commit()
    async with AsyncSessionLocal() as db:
        admin = await db.get(User, d["owner"])
        created = await create_user(
            UserCreate(username="na_newbie", password="secret123", display_name="新人"),
            user=admin, db=db,
        )
        await db.commit()
        new_id = created.id

    async with AsyncSessionLocal() as db:
        u = await db.get(User, new_id)
        perms = await get_user_permission_codes(db, u)
        assert "kb:read" in perms and "chat:use" in perms, perms
        # 且确实带 viewer 角色授予
        ur = (await db.execute(select(UserRole).where(UserRole.user_id == new_id))).scalars().all()
        assert ur, "应自动授予 viewer 角色"
    print("OK create_user_viewer")


async def _password_change():
    d = await _setup()
    from app.api.v1.auth import change_password
    from app.core.errors import ValidationError
    from app.core.security import verify_password
    from app.schemas.auth import PasswordChangeRequest

    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["outsider"])
        # 旧密码错 → 拒绝
        try:
            await change_password(PasswordChangeRequest(old_password="wrong", new_password="newpass1"), user=user, db=db)
            raise AssertionError("旧密码错误应被拒")
        except ValidationError:
            pass
        # 正确 → 生效
        await change_password(PasswordChangeRequest(old_password="x", new_password="newpass1"), user=user, db=db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["outsider"])
        assert verify_password("newpass1", user.password_hash)
    print("OK password_change")


async def _me_roles():
    d = await _setup()
    from app.api.v1.auth import me

    async with AsyncSessionLocal() as db:
        user = await db.get(User, d["member_u"])
        out = await me(user=user, db=db)
        assert out.permissions is not None
        assert isinstance(out.roles, list)
    print("OK me_roles")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_doc_read_requires_kb_membership():
    _run_async(_read_outsider_blocked())


def test_doc_read_member_ok():
    _run_async(_read_readmember_ok())


def test_doc_edit_by_department():
    _run_async(_edit_by_department_principal())


def test_doc_edit_by_role():
    _run_async(_edit_by_role_principal())


def test_effective_perm():
    _run_async(_effective_perm_levels())


def test_create_user_grants_viewer():
    _run_async(_create_user_grants_viewer())


def test_password_change():
    _run_async(_password_change())


def test_me_has_roles():
    _run_async(_me_roles())
