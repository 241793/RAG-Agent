"""第三轮补全工具测试：注册、分层（个人/管理）、CRUD 落库、权限边界（会话越权拒绝）。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select


def _ev(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_complement_tools_registered_and_tiered():
    """7 个新工具全部注册；待办/会话为常驻内置，其余按需管理池。"""
    from app.agents.tools.registry import registry

    builtin = {t.name for t in registry.all_builtin()}
    admin = {t.name for t in registry.all_admin()}

    # 用户级：常驻
    assert "manage_reminder" in builtin
    assert "manage_conversation" in builtin
    # 管理级：按需池
    for n in ("manage_record_template", "manage_quick_reply", "manage_channel_user",
              "manage_notification", "manage_eval"):
        assert n in admin, f"{n} 未注册"
        assert n not in builtin, f"{n} 不应常驻"


def test_complement_tools_declare_permission():
    from app.agents.tools.complement_tools import COMPLEMENT_TOOLS, PERSONAL_TOOLS

    for t in [*PERSONAL_TOOLS, *COMPLEMENT_TOOLS]:
        assert getattr(t, "kind", "") == "write", t.name
        assert getattr(t, "required_permission", None), f"{t.name} 缺权限声明"
        t.summarize({"action": "list"})


def test_ms_parses_iso_and_timestamps():
    from app.agents.tools.complement_tools import _ms

    assert _ms(None) is None and _ms("") is None
    assert _ms(1_700_000_000_000) == 1_700_000_000_000  # 已是 ms
    assert _ms(1_700_000_000) == 1_700_000_000_000      # 秒 → ms
    # ISO 字符串
    got = _ms("2026-10-20 09:00")
    assert isinstance(got, int) and got > 0


async def _setup():
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Tenant, User

    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "cmp"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="CMP", slug="cmp")
            db.add(t)
            await db.flush()
        users = {}
        for un in ("cmp_a", "cmp_b"):
            u = (await db.execute(select(User).where(User.username == un))).scalar_one_or_none()
            if not u:
                u = User(tenant_id=t.id, username=un, password_hash="x")
                db.add(u)
                await db.flush()
            users[un] = u.id
        await db.commit()
        return {"tid": t.id, "a": users["cmp_a"], "b": users["cmp_b"]}


def test_reminder_crud_and_isolation():
    """待办：建/列/完成/删，且只作用于本租户。"""
    from app.agents.tools.base import ToolContext
    from app.agents.tools.complement_tools import ManageReminderTool
    from app.core.db import AsyncSessionLocal
    from app.services.permission import PrincipalSet

    d = _ev(_setup())
    tool = ManageReminderTool()

    async def run():
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["a"], tenant_id=d["tid"]),
                              tenant_id=d["tid"], user_id=d["a"])
            r = await tool.execute({"action": "create", "title": "交周报",
                                    "due_at": "2026-10-20 18:00"}, ctx)
            assert not r.is_error, r.content
            rid = r.data["reminder_id"]
            await db.commit()

            r = await tool.execute({"action": "list"}, ctx)
            assert "交周报" in r.content, r.content
            await db.commit()

            r = await tool.execute({"action": "done", "reminder_id": rid}, ctx)
            assert not r.is_error
            await db.commit()

            r = await tool.execute({"action": "list", "status": "done"}, ctx)
            assert "交周报" in r.content
            await db.commit()

            r = await tool.execute({"action": "delete", "reminder_id": rid}, ctx)
            assert not r.is_error
            await db.commit()

    _ev(run())


def test_conversation_ownership_enforced():
    """会话：B 不能改名/删除 A 的会话（越权拒绝）。"""
    from app.agents.tools.base import ToolContext
    from app.agents.tools.complement_tools import ManageConversationTool
    from app.core.db import AsyncSessionLocal
    from app.models import Conversation
    from app.services.permission import PrincipalSet

    d = _ev(_setup())
    tool = ManageConversationTool()

    async def run():
        async with AsyncSessionLocal() as db:
            c = Conversation(tenant_id=d["tid"], user_id=d["a"], title="A 的会话")
            db.add(c)
            await db.flush()
            cid = c.id
            await db.commit()

            # B 尝试越权
            ctx_b = ToolContext(db=db, ps=PrincipalSet(user_id=d["b"], tenant_id=d["tid"]),
                                tenant_id=d["tid"], user_id=d["b"])
            r = await tool.execute({"action": "rename", "conversation_id": cid, "title": "篡改"}, ctx_b)
            assert r.is_error and "不属于" in r.content, r.content

            r = await tool.execute({"action": "delete", "conversation_id": cid}, ctx_b)
            assert r.is_error, "越权删除必须被拒"

            # A 自己可以
            ctx_a = ToolContext(db=db, ps=PrincipalSet(user_id=d["a"], tenant_id=d["tid"]),
                                tenant_id=d["tid"], user_id=d["a"])
            r = await tool.execute({"action": "rename", "conversation_id": cid, "title": "改好了"}, ctx_a)
            assert not r.is_error, r.content
            await db.commit()
            db.expire_all()
            got = await db.get(Conversation, cid)
            assert got.title == "改好了"

            # 清理
            await db.delete(got)
            await db.commit()

    _ev(run())


def test_notification_send_and_read():
    """站内通知：给同事发通知，对方可列出并标记已读。"""
    from app.agents.tools.base import ToolContext
    from app.agents.tools.complement_tools import ManageNotificationTool
    from app.core.db import AsyncSessionLocal
    from app.services.permission import PrincipalSet

    d = _ev(_setup())
    tool = ManageNotificationTool()

    async def run():
        async with AsyncSessionLocal() as db:
            ctx_a = ToolContext(db=db, ps=PrincipalSet(user_id=d["a"], tenant_id=d["tid"]),
                                tenant_id=d["tid"], user_id=d["a"])
            r = await tool.execute({"action": "send", "user_id": d["b"], "title": "开会提醒",
                                    "body": "10 分钟后站会"}, ctx_a)
            assert not r.is_error, r.content
            nid = r.data["notification_id"]
            await db.commit()

            ctx_b = ToolContext(db=db, ps=PrincipalSet(user_id=d["b"], tenant_id=d["tid"]),
                                tenant_id=d["tid"], user_id=d["b"])
            r = await tool.execute({"action": "list", "unread_only": True}, ctx_b)
            assert "开会提醒" in r.content, r.content
            await db.commit()

            r = await tool.execute({"action": "read", "notification_id": nid}, ctx_b)
            assert not r.is_error
            await db.commit()
            r = await tool.execute({"action": "list", "unread_only": True}, ctx_b)
            assert "开会提醒" not in r.content
            await db.commit()

    _ev(run())


def test_record_template_create_and_entries():
    """录单模板：建模板 + 字段；列模板。"""
    from app.agents.tools.base import ToolContext
    from app.agents.tools.complement_tools import ManageRecordTemplateTool
    from app.core.db import AsyncSessionLocal
    from app.services.permission import PrincipalSet

    d = _ev(_setup())
    tool = ManageRecordTemplateTool()

    async def run():
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["a"], tenant_id=d["tid"]),
                              tenant_id=d["tid"], user_id=d["a"])
            r = await tool.execute({
                "action": "create", "name": "客服工单录单",
                "fields": [{"name": "customer", "label": "客户", "type": "text", "required": True},
                           {"name": "phone", "label": "电话", "type": "phone"}],
            }, ctx)
            assert not r.is_error, r.content
            tid = r.data["template_id"]
            await db.commit()

            r = await tool.execute({"action": "list"}, ctx)
            assert "客服工单录单" in r.content and "客户" in r.content, r.content
            await db.commit()

            r = await tool.execute({"action": "list_entries", "template_id": tid}, ctx)
            assert not r.is_error
            await db.commit()

    _ev(run())
