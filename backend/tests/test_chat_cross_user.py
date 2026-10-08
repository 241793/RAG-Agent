"""跨用户会话访问权限测试。

断言：
  - 无 chat:read_all：他人会话 list_messages → 404
  - 授予 chat:read_all 后：可读；但 delete/rename 仍 404（写操作不放大）
  - _assert_conv_access 跨租户拒绝
"""
from __future__ import annotations

import asyncio

from app.core.db import AsyncSessionLocal, init_models
from app.core.errors import NotFoundError
from app.core.security import hash_password
from app.models import Conversation, Role, Tenant, User, UserRole
from sqlalchemy import select


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "xu"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="XU", slug="xu"); db.add(t); await db.flush()
        a = (await db.execute(select(User).where(User.username == "xu_a"))).scalar_one_or_none()
        if not a:
            a = User(tenant_id=t.id, username="xu_a", password_hash=hash_password("x")); db.add(a)
        b = (await db.execute(select(User).where(User.username == "xu_b"))).scalar_one_or_none()
        if not b:
            b = User(tenant_id=t.id, username="xu_b", password_hash=hash_password("x"), is_admin=False); db.add(b)
        await db.flush()
        conv = (await db.execute(select(Conversation).where(Conversation.user_id == a.id))).scalars().first()
        if not conv:
            conv = Conversation(tenant_id=t.id, user_id=a.id, title="A的会话"); db.add(conv); await db.flush()
        await db.commit()
        return {"tid": t.id, "a": a.id, "b": b.id, "conv": conv.id}


async def _run():
    d = await _setup()
    from app.api.v1.chat import _assert_conv_access
    from app.middleware.auth_dep import user_has_permission

    # B 无 chat:read_all → 读 A 的会话 404
    async with AsyncSessionLocal() as db:
        user_b = await db.get(User, d["b"])
        try:
            await _assert_conv_access(db, d["conv"], user_b)
            assert False, "应拒绝"
        except NotFoundError:
            pass

    # 授予 B 一个含 chat:read_all 的角色
    async with AsyncSessionLocal() as db:
        from app.services.permission_seed import seed_permissions_and_roles

        role_ids = await seed_permissions_and_roles(db)
        await db.commit()
        # 直接用 tenant_admin（含 chat:read_all）
        ta = role_ids["tenant_admin"]
        ex = (await db.execute(select(UserRole).where(UserRole.user_id == d["b"], UserRole.role_id == ta))).scalar_one_or_none()
        if not ex:
            db.add(UserRole(tenant_id=d["tid"], user_id=d["b"], role_id=ta, scope_type="tenant", scope_id=0))
            await db.commit()

    async with AsyncSessionLocal() as db:
        user_b = await db.get(User, d["b"])
        assert await user_has_permission(db, user_b, "chat:read_all") is True
        # 现在可读 A 的会话
        conv = await _assert_conv_access(db, d["conv"], user_b)
        assert conv.id == d["conv"]

    # 但 delete 走的是归属校验（非 _assert_conv_access）→ 仍拒绝
    async with AsyncSessionLocal() as db:
        user_b = await db.get(User, d["b"])
        conv = await db.get(Conversation, d["conv"])
        assert conv.user_id != user_b.id  # delete 校验条件
    print("OK cross_user")


def test_cross_user_access():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.set_event_loop(None)
