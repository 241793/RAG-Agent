"""外部客户与内部用户分离 + 三个安全漏洞修复验证。

漏洞：
1. 渠道用户走 Agent 模式默认拿 {"*"} 工具权限 → 可调管理工具（权限提升）
2. filter_accessible_kbs 无条件放行 internal → 外部客户读内部库（越权）
3. 外部虚拟用户混入用户管理列表（污染）
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Channel, ChannelUser, KnowledgeBase, Tenant, User
from app.services.permission import PrincipalSet, filter_accessible_kbs


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "ext"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="EXT", slug="ext"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "ext_internal"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="ext_internal", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id}


# ---- 1. 工具权限：默认空集 ----
def test_runner_default_perms_empty():
    """AgentRunner 未传 perms → 空集（不再是通配）。"""
    from app.agents.runner import AgentRunner

    class FakeAgent:
        id = 1
    ps = PrincipalSet(user_id=1, tenant_id=1)
    r = AgentRunner(None, agent=FakeAgent(), ps=ps, conversation=None)
    assert r.perms == set(), "默认 perms 应为空集"


def test_channel_user_gets_no_admin_tools():
    """渠道外部用户（无角色）→ resolve_tools 不返回任何 admin 工具。"""
    async def _run():
        d = await _setup()
        from app.agents.tools.registry import registry, resolve_tools
        from app.middleware.auth_dep import get_user_permission_codes
        from app.models import Channel

        async with AsyncSessionLocal() as db:
            ch = (await db.execute(select(Channel).where(Channel.name == "ext_ch"))).scalar_one_or_none()
            if not ch:
                ch = Channel(tenant_id=d["tenant_id"], kind="wework", name="ext_ch", enabled=True)
                db.add(ch); await db.flush()
            # 模拟渠道外部用户
            ext = User(tenant_id=d["tenant_id"], username="wework_ext1",
                       password_hash=hash_password("x"), user_type="external")
            db.add(ext); await db.flush()
            await db.commit()
            perms = await get_user_permission_codes(db, ext)
            assert perms == set(), f"外部用户应无权限码，实际 {perms}"
            cfg = {"builtin": {t.name: {"enabled": True} for t in registry.all_builtin()},
                   "admin": {"enabled": True}}
            tools = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=d["tenant_id"], perms=perms)
            admin_names = {t.name for t in registry.all_admin()}
            leaked = [t.name for t in tools if t.name in admin_names]
            assert not leaked, f"外部用户不应拿到管理工具: {leaked}"
    asyncio.new_event_loop().run_until_complete(_run())


# ---- 2. internal 库越权 ----
def test_filter_accessible_kbs_external_blocks_internal():
    rows = [
        {"kb_id": 1, "visibility": "public", "principals": []},
        {"kb_id": 2, "visibility": "internal", "principals": []},
        {"kb_id": 3, "visibility": "private", "principals": []},
    ]
    # 外部主体：只 public，不含 internal/private
    ext = PrincipalSet(user_id=10, tenant_id=1, is_external=True)
    assert set(filter_accessible_kbs(ext, rows)) == {1}
    # 内部主体：public + internal
    internal = PrincipalSet(user_id=11, tenant_id=1, is_external=False)
    assert set(filter_accessible_kbs(internal, rows)) == {1, 2}
    # 外部主体的显式成员库可见
    rows2 = [{"kb_id": 5, "visibility": "private", "principals": [1_000_000_000_010]}]
    assert filter_accessible_kbs(ext, rows2) == [5]  # user_id=10 的 principal 命中


def test_external_cannot_access_internal_kb_via_api():
    """_ensure_access：外部主体访问 internal 库被拒。"""
    async def _run():
        d = await _setup()
        from app.api.v1.kb import _ensure_access
        from app.core.errors import PermissionDeniedError

        async with AsyncSessionLocal() as db:
            kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "ext_internal_kb"))).scalar_one_or_none()
            if not kb:
                kb = KnowledgeBase(tenant_id=d["tenant_id"], name="ext_internal_kb",
                                   visibility="internal", embedding_dim=64, owner_id=d["user_id"])
                db.add(kb); await db.flush(); await db.commit()
            ext = PrincipalSet(user_id=999, tenant_id=d["tenant_id"], is_external=True)
            with pytest.raises(PermissionDeniedError):
                await _ensure_access(db, ext, kb)
            # 内部用户放行
            await _ensure_access(db, PrincipalSet(user_id=998, tenant_id=d["tenant_id"]), kb)
    asyncio.new_event_loop().run_until_complete(_run())


# ---- 3. 用户列表过滤 ----
def test_external_user_hidden_from_list():
    async def _run():
        d = await _setup()
        from app.api.v1.rbac import list_users

        async with AsyncSessionLocal() as db:
            # 确保有一个外部用户
            ext = (await db.execute(select(User).where(User.username == "wework_ext1"))).scalar_one_or_none()
            assert ext is not None and ext.user_type == "external"
            admin = await db.get(User, d["user_id"])
            result = await list_users(page=1, page_size=100, search=None, status=None, user=admin, db=db)
            usernames = [it.username for it in result["items"]]
            assert "wework_ext1" not in usernames, "外部用户不应出现在用户列表"
            assert all(getattr(it, "username", "") != "wework_ext1" for it in result["items"])
    asyncio.new_event_loop().run_until_complete(_run())


# ---- 4. 建模：渠道虚拟用户标记 ----
def test_resolve_channel_user_marks_external():
    async def _run():
        d = await _setup()
        from app.services.channel_service import principal_of, resolve_channel_user

        async with AsyncSessionLocal() as db:
            ch = (await db.execute(select(Channel).where(Channel.name == "ext_ch"))).scalar_one()
            cu, user, bound = await resolve_channel_user(db, channel=ch, external_id="newcustomer_xyz")
            await db.commit()
            assert user.user_type == "external"
            assert bound is None
            assert principal_of(user).is_external is True
            assert principal_of(user).is_admin is False
    asyncio.new_event_loop().run_until_complete(_run())


def test_principal_set_is_external_default():
    assert PrincipalSet(user_id=1, tenant_id=1).is_external is False
    assert PrincipalSet(user_id=1, tenant_id=1, is_external=True).is_external is True
