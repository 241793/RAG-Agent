"""SSO 建号（JIT）的权限兜底测试。

回归重点：未配置 default_role_ids 时，新建的 SSO 用户**必须**拿到内置
「普通用户」角色。否则其权限集为空 → 登录后全站 403，
表现为「SSO 能登进去但什么都打不开」。
"""
from __future__ import annotations

import asyncio
import time

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.middleware.auth_dep import get_user_permission_codes
from app.models import Role, Tenant, User, UserRole
from sqlalchemy import select


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _ensure_viewer_role(db) -> None:
    """确保内置角色已存在。

    测试库每次运行前被重建，init_models() 只建表、不种数据（生产由
    run_server.py 的 seed_all() 完成）。缺 viewer 会让兜底授予静默失效。
    """
    from app.services.permission_seed import seed_permissions_and_roles

    existing = (await db.execute(select(Role).where(Role.code == "viewer"))).scalars().first()
    if not existing:
        await seed_permissions_and_roles(db)
        await db.commit()


async def _make_tenant_user(provider: str, subject: str) -> tuple[int, int]:
    await init_models()
    async with AsyncSessionLocal() as db:
        await _ensure_viewer_role(db)
        t = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
        if not t:
            t = Tenant(name="SSO_JIT", slug="ssojit")
            db.add(t)
            await db.flush()
        u = User(
            tenant_id=t.id,
            username=f"sso_t_{subject}_{int(time.time() * 1000) % 10**7}",
            password_hash=hash_password("x"),
            display_name="SSO 测试",
            sso_provider=provider,
            sso_subject=subject,
            status="active",
            approval_status="approved",
        )
        db.add(u)
        await db.flush()
        uid, tid = u.id, u.tenant_id
        await db.commit()
        return uid, tid


async def _grant_viewer(db, tenant_id: int, user_id: int) -> None:
    from app.api.v1.rbac import _grant_default_viewer_role

    await _grant_default_viewer_role(db, tenant_id=tenant_id, user_id=user_id)


async def _perms(uid: int) -> set[str]:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == uid))).scalar_one()
        return await get_user_permission_codes(db, u)


async def _cleanup(uid: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(UserRole.__table__.delete().where(UserRole.user_id == uid))
        await db.execute(User.__table__.delete().where(User.id == uid))
        await db.commit()


def test_sso_user_without_role_has_empty_perms():
    """先证明问题存在：不授角色时权限集为空（这正是修复前的行为）。"""
    uid, _ = _run(_make_tenant_user("dingtalk", "empty_probe"))
    try:
        perms = _run(_perms(uid))
        assert perms == set(), "未授角色时应为空 —— 这条断言说明兜底是必要的"
    finally:
        _run(_cleanup(uid))


def test_grant_default_viewer_role_fills_perms():
    """兜底授予后，权限集必须非空且含 chat:use（否则全站 403）。

    注意：必须在**同一个事件循环**内完成「建号→授权→查权限」。
    async 引擎绑定在创建它的事件循环上，拆成多个 new_event_loop() 会各自
    拿到不同循环，导致连接/会话错乱（表现为权限查不到）。
    """

    async def _go():
        await init_models()
        # 1) 建号 + 兜底授予（写入后提交）
        async with AsyncSessionLocal() as db:
            await _ensure_viewer_role(db)
            t = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
            if not t:
                t = Tenant(name="SSO_JIT2", slug="ssojit2")
                db.add(t)
                await db.flush()
            tid = t.id
            u = User(
                tenant_id=tid,
                username=f"sso_g_{int(time.time() * 1000) % 10**7}",
                password_hash=hash_password("x"),
                sso_provider="dingtalk",
                sso_subject="granted_probe",
                status="active",
                approval_status="approved",
            )
            db.add(u)
            await db.flush()
            uid = u.id

            from app.api.v1.rbac import _grant_default_viewer_role

            # 不假设「必定新增」：SQLite 会复用已删除行的 id，可能与历史授予撞车。
            # 真正要保证的是「调用后一定拥有 viewer 权限」。
            await _grant_default_viewer_role(db, tenant_id=tid, user_id=uid)
            await db.commit()

        # 2) 用**全新 session** 复查（模拟真实请求路径；同 session 内复用对象
        #    可能读到未刷新的状态，导致误判为空）
        async with AsyncSessionLocal() as db2:
            u2 = (await db2.execute(select(User).where(User.id == uid))).scalar_one()
            perms = await get_user_permission_codes(db2, u2)
            assert perms, "兜底授予后权限集不得为空"
            assert "chat:use" in perms, "缺 chat:use 会导致登录后全站 403"

            # 幂等：重复授予不应产生第二条 viewer
            from app.api.v1.rbac import _grant_default_viewer_role

            await _grant_default_viewer_role(db2, tenant_id=u2.tenant_id, user_id=uid)
            await db2.commit()
            vr = (await db2.execute(select(Role).where(Role.code == "viewer"))).scalars().first()
            cnt = (
                await db2.execute(
                    select(UserRole).where(
                        UserRole.user_id == uid, UserRole.role_id == vr.id
                    )
                )
            ).scalars().all()
            assert len(cnt) == 1, f"viewer 授予应恰有一条，实际 {len(cnt)}"

            # 清理
            await db2.execute(UserRole.__table__.delete().where(UserRole.user_id == uid))
            await db2.execute(User.__table__.delete().where(User.id == uid))
            await db2.commit()

    _run(_go())


def test_sso_callback_grants_viewer_when_no_default_roles():
    """源码级回归：sso_callback 在未配置默认角色时必须调用兜底授予。

    该路径依赖真实 IdP 回调，难以端到端触发，故用源码断言守住。
    """
    import inspect

    from app.api.v1 import sso

    src = inspect.getsource(sso.sso_callback)
    assert "_grant_default_viewer_role" in src, "SSO 建号缺少权限兜底 → 用户会全站 403"
    # 且必须是「未授予任何角色时」才兜底，避免覆盖管理员显式配置
    assert "not granted" in src or "if not granted" in src


def test_configs_api_returns_new_user_fields():
    """配置接口必须回传 auto_create_user / default_role_ids，否则前端无法回显。"""
    import inspect

    from app.api.v1 import sso

    src = inspect.getsource(sso.list_configs)
    assert "auto_create_user" in src
    assert "default_role_ids" in src
