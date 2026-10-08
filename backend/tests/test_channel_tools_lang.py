"""渠道外部客户：只读工具规则 + 多语言客服。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.registry import registry, resolve_tools
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Tenant, User


def test_external_only_gets_read_tools():
    """外部客户 resolve_tools 只返回 kind==read 的工具，绝不返回 write/admin。"""
    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "exttool"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="ET", slug="exttool"); db.add(t); await db.flush(); await db.commit()
            cfg = {"builtin": {x.name: {"enabled": True} for x in registry.all_builtin()}, "admin": {"enabled": True}}
            # 外部客户：给足权限码（模拟误授），仍只应拿到 read 工具
            perms = {"*"}
            ext = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=t.id, perms=perms, is_external=True)
            assert all(getattr(x, "kind", "read") == "read" for x in ext), \
                f"外部客户拿到了非只读工具: {[(x.name, getattr(x,'kind',None)) for x in ext if getattr(x,'kind','read')!='read']}"
            # 内部用户（同权限）拿到全部
            internal = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=t.id, perms=perms, is_external=False)
            assert len(internal) > len(ext)
    asyncio.new_event_loop().run_until_complete(_run())


def test_external_no_admin_tools_even_with_wildcard():
    """外部客户即使有 * 权限码，也不返回任何 admin（管理类）工具。"""
    async def _run():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).where(Tenant.slug == "exttool"))).scalar_one()
            cfg = {"admin": {"enabled": True}}
            ext = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=t.id, perms={"*"}, is_external=True)
            admin_names = {x.name for x in registry.all_admin()}
            leaked = [x.name for x in ext if x.name in admin_names]
            assert not leaked, f"外部客户拿到管理工具: {leaked}"
    asyncio.new_event_loop().run_until_complete(_run())


def test_detect_lang():
    from app.channels.commands import detect_lang

    assert detect_lang("hello where is my order") == "en"
    assert detect_lang("我的订单在哪里") == "zh"
    assert detect_lang("こんにちは、注文はどこですか") == "ja"


def test_lang_command():
    from app.channels.commands import COMMANDS, cmd_lang

    assert "lang" in COMMANDS

    class CU:
        lang = None
    cu = CU()

    class Ctx:
        channel_user = cu
        channel = type("C", (), {"name": "test", "kind": "wework"})()
        external_group = None

        class db:
            @staticmethod
            async def flush(): pass

    async def _run():
        r = await cmd_lang(Ctx(), ["en"])
        assert "English" in r and cu.lang == "en"
        r2 = await cmd_lang(Ctx(), ["auto"])
        assert cu.lang is None
    asyncio.new_event_loop().run_until_complete(_run())


def test_service_agent_role_grants_tool_invoke():
    from app.services.permission_seed import ROLES

    role = next((r for r in ROLES if r[0] == "service_agent"), None)
    assert role is not None
    perms = role[3]
    assert "tool:invoke" in perms and "chat:use" in perms
    # 不含任何写权限
    assert not any(p.endswith((":edit", ":manage", ":create", ":delete")) for p in perms)


def test_with_lang_instruction():
    from app.channels.dispatcher import _with_lang

    assert "English" in _with_lang("hi", "en")
    assert _with_lang("hi", None) == "hi"
    assert _with_lang("hi", "xx") == "hi"  # 未知语言不注入
