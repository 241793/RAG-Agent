"""渠道身份绑定：外部身份 → 内部账号，绑定后继承真实权限。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Channel, ChannelUser, Tenant, User, UserRole, Role
from app.services.channel_service import principal_of, resolve_channel_user
from app.services.permission import PrincipalSet


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "bind"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="BIND", slug="bind"); db.add(t); await db.flush()
        admin = (await db.execute(select(User).where(User.username == "bind_admin"))).scalar_one_or_none()
        if not admin:
            admin = User(tenant_id=t.id, username="bind_admin", password_hash=hash_password("x"),
                         display_name="管理员", is_admin=True, user_type="internal")
            db.add(admin); await db.flush()
        staff = (await db.execute(select(User).where(User.username == "bind_staff"))).scalar_one_or_none()
        if not staff:
            staff = User(tenant_id=t.id, username="bind_staff", password_hash=hash_password("x"),
                         display_name="同事", is_admin=False, user_type="internal")
            db.add(staff); await db.flush()
        ch = (await db.execute(select(Channel).where(Channel.name == "bind_ch"))).scalar_one_or_none()
        if not ch:
            ch = Channel(tenant_id=t.id, kind="wework", name="bind_ch", enabled=True); db.add(ch); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "admin": admin.id, "staff": staff.id, "channel_id": ch.id}


def test_unbound_user_is_external_readonly():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            ch = await db.get(Channel, d["channel_id"])
            cu, user, bound = await resolve_channel_user(db, channel=ch, external_id="ext_cust")
            await db.commit()
            assert user.user_type == "external" and bound is None
            ps = principal_of(user, bound)
            assert ps.is_external is True and ps.is_admin is False
    asyncio.new_event_loop().run_until_complete(_run())


def test_bound_admin_inherits_admin():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            ch = await db.get(Channel, d["channel_id"])
            cu, user, bound = await resolve_channel_user(db, channel=ch, external_id="ext_boss")
            # 绑定到管理员账号
            cu.bound_user_id = d["admin"]
            await db.commit()
        async with AsyncSessionLocal() as db:
            ch = await db.get(Channel, d["channel_id"])
            cu, user, bound = await resolve_channel_user(db, channel=ch, external_id="ext_boss")
            assert bound is not None and bound.id == d["admin"]
            ps = principal_of(user, bound)
            assert ps.is_admin is True and ps.is_external is False  # 继承管理员
    asyncio.new_event_loop().run_until_complete(_run())


def test_channel_user_perms_inherit(monkeypatch):
    async def _run():
        d = await _setup()
        from app.agents.tools.registry import registry, resolve_tools
        from app.middleware.auth_dep import get_user_permission_codes
        from app.channels.dispatcher import _channel_user_perms

        async with AsyncSessionLocal() as db:
            admin = await db.get(User, d["admin"])
            staff = await db.get(User, d["staff"])
            # 管理员绑定 → 权限含 *
            perms_admin = await _channel_user_perms(db, staff, admin)
            assert "*" in perms_admin
            # 未绑定外部用户 → service_agent 档
            ext = User(tenant_id=d["tenant_id"], username="wework_x1", password_hash="x", user_type="external")
            db.add(ext); await db.flush()
            perms_ext = await _channel_user_perms(db, ext)
            assert "chat:use" in perms_ext and "*" not in perms_ext
            # 绑管理员后 resolve_tools 能装管理工具（is_external=False）
            cfg = {"admin": {"enabled": True}}
            tools = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=d["tenant_id"],
                                        perms=perms_admin, is_external=False)
            admin_names = {t.name for t in registry.all_admin()}
            assert any(t.name in admin_names for t in tools)
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_bind_code_command():
    from app.channels.commands import COMMANDS, cmd_bind

    assert "bind" in COMMANDS

    class CU:
        bound_user_id = None
        bind_code = None
    cu = CU()

    class Ctx:
        channel_user = cu
        channel = type("C", (), {"name": "t", "kind": "wework"})()
        class db:
            @staticmethod
            async def flush(): pass

    async def _run():
        r = await cmd_bind(Ctx(), [])
        assert "绑定码" in r and cu.bind_code and len(cu.bind_code) == 6
    asyncio.new_event_loop().run_until_complete(_run())


def test_bind_endpoint_registered():
    from app.api.v1.channels import router

    paths = {r.path.rstrip("/") for r in router.routes}
    assert any("users/{cu_id}/bind" in p for p in paths)


def test_users_list_keeps_null_user_type():
    """回归：user_type 为 NULL 的历史账号不能被「过滤 external」误删。

    SQL 中 NULL != 'external' 求值为 NULL（假），曾导致 /admin/users 漏掉全部历史账号
    （含 admin），使绑定页选不到管理员。此处用可空临时表验证谓词语义。
    生产库中该列由 ALTER 后加，允许 NULL，而新建测试库有 NOT NULL 约束，故另建表。
    """
    async def _run():
        from sqlalchemy import Column, Integer, String, MetaData, Table, or_, select, text

        async with AsyncSessionLocal() as db:
            await db.execute(text("DROP TABLE IF EXISTS _null_probe"))
            await db.execute(text("CREATE TABLE _null_probe (id INTEGER PRIMARY KEY, user_type VARCHAR(16))"))
            await db.execute(text("INSERT INTO _null_probe (id, user_type) VALUES (1, NULL)"))
            await db.execute(text("INSERT INTO _null_probe (id, user_type) VALUES (2, 'internal')"))
            await db.execute(text("INSERT INTO _null_probe (id, user_type) VALUES (3, 'external')"))

            probe = Table("_null_probe", MetaData(),
                          Column("id", Integer, primary_key=True),
                          Column("user_type", String(16)))

            broken = select(probe.c.id).where(probe.c.user_type != "external")
            fixed = select(probe.c.id).where(
                or_(probe.c.user_type.is_(None), probe.c.user_type != "external"))

            broken_ids = {i for (i,) in (await db.execute(broken)).all()}
            fixed_ids = {i for (i,) in (await db.execute(fixed)).all()}
            assert 1 not in broken_ids, "旧查询确实会漏掉 user_type=NULL 的账号"
            assert 1 in fixed_ids and 2 in fixed_ids and 3 not in fixed_ids, \
                "修复后应保留 NULL 与 internal，仅排除 external"
            await db.execute(text("DROP TABLE IF EXISTS _null_probe"))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_channel_rag_enables_tools_only_when_bound(monkeypatch):
    """回归：渠道 RAG 路径仅在绑定内部账号时装工具（未绑定外部客户不装）。

    否则绑定管理员后 AI 仍只能「聊」不能「操作」。
    """
    import app.channels.dispatcher as disp

    captured: dict = {}

    async def fake_stream_answer(db, **kwargs):
        captured.update(kwargs)
        yield {"type": "delta", "text": "ok"}
        yield {"type": "done"}

    class FakeConv:
        id = 1
        kb_ids = []

    class FakeSession:
        async def get(self, model, pk):
            return FakeConv()

    class _Ctx:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("app.services.chat_service.stream_answer", fake_stream_answer)
    monkeypatch.setattr("app.core.db.AsyncSessionLocal", lambda: _Ctx())

    async def _run():
        # 未绑定外部客户：不装工具
        captured.clear()
        await disp._run_rag(PrincipalSet(user_id=99, tenant_id=1, is_external=True),
                            1, "hi", True, use_tools=False)
        assert captured.get("use_tools") is False
        assert captured.get("allow_auto_write") is False
        # 绑定管理员内部账号：装工具 + 写操作直接执行
        captured.clear()
        await disp._run_rag(PrincipalSet(user_id=1, tenant_id=1, is_admin=True),
                            1, "hi", True, use_tools=True)
        assert captured.get("use_tools") is True
        assert captured.get("allow_auto_write") is True

    asyncio.new_event_loop().run_until_complete(_run())

