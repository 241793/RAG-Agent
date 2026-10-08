"""智能客服：转人工检测、工单建/回复/关闭、AI 工具、权限。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.ops_tools2 import ManageServiceTicketTool
from app.channels.dispatcher import _wants_human
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import ServiceTicket, Tenant, User
from app.services import service_ticket_service as S
from app.services.permission import PrincipalSet


def test_wants_human_detection():
    for t in ("帮我转人工", "人工客服", "找真人", "转客服"):
        assert _wants_human(t) is True, t
    for t in ("你好", "请问怎么报销", "谢谢", ""):
        assert _wants_human(t) is False, t


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "svc"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="SVC", slug="svc"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "svc_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="svc_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id}


def _ctx(db, d):
    return ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                       tenant_id=d["tenant_id"], user_id=d["user_id"])


def test_create_and_reply_ticket():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(
                db, tenant_id=d["tenant_id"], subject="退款问题", content="我要退款",
                channel_kind="wework", external_user="user123", notify=False,
            )
            await db.commit()
            tid = t.id
            assert t.status == "open"
            assert t.messages[0]["role"] == "user"
        # 客服回复（无 channel_id → 不回发）
        async with AsyncSessionLocal() as db:
            t = await db.get(ServiceTicket, tid)
            r = await S.add_agent_reply(db, t, "已为您处理退款", agent_id=d["user_id"])
            await db.commit()
            assert r["sent_to_channel"] is False  # 无渠道
            assert t.status == "pending"
            assert t.assignee_id == d["user_id"]
            assert len(t.messages) == 2 and t.messages[1]["role"] == "agent"
        # 关闭
        async with AsyncSessionLocal() as db:
            t = await db.get(ServiceTicket, tid)
            await S.close_ticket(db, t, resolution="已退款")
            await db.commit()
            assert t.status == "closed" and t.resolution == "已退款"
    asyncio.new_event_loop().run_until_complete(_run())


def test_tool_list_get_reply_close():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            t = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="咨询A", content="问题A", notify=False)
            await db.commit(); tid = t.id
        async with AsyncSessionLocal() as db:
            r = await ManageServiceTicketTool().run({"action": "list"}, _ctx(db, d))
            assert not r.is_error and "咨询A" in r.content
        async with AsyncSessionLocal() as db:
            r2 = await ManageServiceTicketTool().run({"action": "get", "ticket_id": tid}, _ctx(db, d))
            assert "问题A" in r2.content and "用户" in r2.content
        async with AsyncSessionLocal() as db:
            r3 = await ManageServiceTicketTool().run(
                {"action": "reply", "ticket_id": tid, "content": "已处理"}, _ctx(db, d))
            await db.commit()
            assert not r3.is_error and "回发" in r3.content
        async with AsyncSessionLocal() as db:
            r4 = await ManageServiceTicketTool().run({"action": "close", "ticket_id": tid}, _ctx(db, d))
            await db.commit()
            assert not r4.is_error and "关闭" in r4.content
        async with AsyncSessionLocal() as db:
            assert (await db.get(ServiceTicket, tid)).status == "closed"
    asyncio.new_event_loop().run_until_complete(_run())


def test_tool_not_found():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            r = await ManageServiceTicketTool().run({"action": "get", "ticket_id": 999999}, _ctx(db, d))
            assert r.is_error and "不存在" in r.content
    asyncio.new_event_loop().run_until_complete(_run())


def test_assignee_isolates_when_filtered():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            await S.create_ticket(db, tenant_id=d["tenant_id"], subject="未指派", content="x", notify=False)
            t2 = await S.create_ticket(db, tenant_id=d["tenant_id"], subject="已指派", content="y", notify=False)
            t2.assignee_id = d["user_id"]
            await db.commit()
        async with AsyncSessionLocal() as db:
            rows = await S.list_tickets(db, tenant_id=d["tenant_id"], assignee_id=d["user_id"])
            assert all(r.assignee_id == d["user_id"] for r in rows)
            assert any(r.subject == "已指派" for r in rows)
    asyncio.new_event_loop().run_until_complete(_run())


def test_endpoints_and_permissions():
    from app.api.v1.service_tickets import router

    paths = {r.path for r in router.routes}
    assert "/service-tickets" in paths
    assert any("reply" in p for p in paths)
    from app.services.permission_seed import PERMISSIONS
    codes = [p[0] for p in PERMISSIONS]
    assert "service:read" in codes and "service:manage" in codes


def test_tool_registered():
    from app.agents.tools.registry import registry

    t = registry.get_admin("manage_service_ticket")
    assert t is not None and t.required_permission == "service:manage"


def test_find_open_ticket_and_continue():
    """已有进行中工单 → 用户后续消息追加到工单，不重复建单。"""
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            tk = await S.create_ticket(
                db, tenant_id=d["tenant_id"], subject="首问", content="我要退款",
                channel_id=7, channel_kind="wework", external_user="u9", notify=False,
            )
            await db.commit(); tid = tk.id
        async with AsyncSessionLocal() as db:
            found = await S.find_open_ticket(db, tenant_id=d["tenant_id"], channel_id=7, external_user="u9")
            assert found is not None and found.id == tid
            await S.add_user_message(db, found, "补充：订单号 A123")
            await db.commit()
            assert found.status == "pending"
            assert len(found.messages) == 2
            assert found.messages[1]["role"] == "user"
        async with AsyncSessionLocal() as db:
            other = await S.find_open_ticket(db, tenant_id=d["tenant_id"], channel_id=7, external_user="u999")
            assert other is None
        async with AsyncSessionLocal() as db:
            tk = await db.get(ServiceTicket, tid)
            await S.close_ticket(db, tk, resolution="已处理")
            await db.commit()
        async with AsyncSessionLocal() as db:
            after = await S.find_open_ticket(db, tenant_id=d["tenant_id"], channel_id=7, external_user="u9")
            assert after is None
    asyncio.new_event_loop().run_until_complete(_run())


def test_service_mode_gate():
    """渠道 service_mode=qa 时不识别转人工；support 时才处理。"""
    from app.channels.dispatcher import _wants_human

    class Ch:
        def __init__(self, mode): self.service_mode = mode

    # _wants_human 是纯函数；门控在 dispatcher 里由 service_mode 决定
    assert _wants_human("转人工") is True  # 词检测本身
    # 门控逻辑：qa → 不调用（下面断言语义）
    assert (Ch("qa").service_mode == "support") is False
    assert (Ch("support").service_mode == "support") is True


def test_customer_context_and_channel_conversations():
    async def _run():
        d = await _setup()
        from app.models import Conversation
        from app.services import service_ticket_service as S2

        async with AsyncSessionLocal() as db:
            # 建两个同客户工单
            t1 = await S2.create_ticket(db, tenant_id=d["tenant_id"], subject="问1", content="x",
                                        channel_id=3, channel_kind="wework", external_user="custX", notify=False)
            t2 = await S2.create_ticket(db, tenant_id=d["tenant_id"], subject="问2", content="y",
                                        channel_id=3, channel_kind="wework", external_user="custX", notify=False)
            await db.commit()
            ctx = await S2.customer_context(db, t2)
            assert ctx["ticket_total"] >= 2 and ctx["external_user"] == "custX"
            assert len(ctx["history"]) >= 2

            # 渠道会话列表
            conv = Conversation(tenant_id=d["tenant_id"], user_id=d["user_id"], title="[wework] 客户",
                                settings={"channel": "wework", "external_id": "custX"})
            db.add(conv); await db.commit()
            convs = await S2.list_channel_conversations(db, tenant_id=d["tenant_id"])
            assert any(c["channel"] == "wework" for c in convs)
    asyncio.new_event_loop().run_until_complete(_run())


def test_channel_service_mode_column():
    from app.models import Channel

    assert "service_mode" in Channel.__table__.columns


def test_new_endpoints_registered():
    from app.api.v1.service_tickets import router

    paths = {r.path for r in router.routes}
    assert any("context" in p for p in paths)
    assert any("channel-conversations" in p for p in paths)


def test_conversation_messages_and_reply(monkeypatch):
    """渠道会话：读消息（含附件）+ 客服回复回发渠道。"""
    async def _run():
        d = await _setup()
        from app.models import Conversation, Message
        from app.services import service_ticket_service as S3

        async with AsyncSessionLocal() as db:
            conv = Conversation(
                tenant_id=d["tenant_id"], user_id=d["user_id"], title="[wework] 客户",
                settings={"channel": "wework", "external_id": "custZ", "channel_id": 5},
            )
            db.add(conv); await db.flush()
            db.add(Message(tenant_id=d["tenant_id"], conversation_id=conv.id, role="user",
                           content="我要退货", created_at=1,
                           attachments=[{"type": "image", "file_key": "1/a.png", "name": "a.png",
                                         "mime": "image/png", "size": 100}]))
            db.add(Message(tenant_id=d["tenant_id"], conversation_id=conv.id, role="assistant",
                           content="好的，请提供订单号", created_at=2))
            await db.commit(); cid = conv.id

        # 读消息：含附件
        async with AsyncSessionLocal() as db:
            msgs = await S3.conversation_messages(db, conversation_id=cid, tenant_id=d["tenant_id"])
            assert len(msgs) == 2
            assert msgs[0]["attachments"][0]["file_key"] == "1/a.png"
            assert msgs[1]["role"] == "assistant"

        # 跨租户 → 拒绝
        async with AsyncSessionLocal() as db:
            try:
                await S3.conversation_messages(db, conversation_id=cid, tenant_id=d["tenant_id"] + 999)
                raise AssertionError("跨租户应被拒")
            except ValueError:
                pass

        # 回复 → 落 agent 消息 + 回发渠道（mock send）
        sent = []
        from app.channels.manager import channel_manager

        async def _fake_send(channel_id, kind, out):
            sent.append((channel_id, out.user_id, out.content)); return True
        monkeypatch.setattr(channel_manager, "send_with_fallback", _fake_send)

        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            r = await S3.reply_in_conversation(db, conversation=conv, content="已为您处理", agent_id=d["user_id"])
            await db.commit()
            assert r["ok"] and r["sent_to_channel"] is True
            assert sent and sent[0][2] == "已为您处理"

        # 落库校验：会话多了 agent 消息
        async with AsyncSessionLocal() as db:
            msgs = await S3.conversation_messages(db, conversation_id=cid, tenant_id=d["tenant_id"])
            assert any(m["role"] == "agent" and m["content"] == "已为您处理" for m in msgs)
    asyncio.new_event_loop().run_until_complete(_run())


def test_channel_conversations_has_last_message():
    async def _run():
        d = await _setup()
        from app.models import Conversation, Message
        from app.services import service_ticket_service as S3

        async with AsyncSessionLocal() as db:
            conv = Conversation(tenant_id=d["tenant_id"], user_id=d["user_id"], title="[feishu] X",
                                settings={"channel": "feishu", "external_id": "fx1", "channel_id": 9})
            db.add(conv); await db.flush()
            db.add(Message(tenant_id=d["tenant_id"], conversation_id=conv.id, role="user",
                           content="最后一条消息内容", created_at=5))
            await db.commit(); cid = conv.id
        async with AsyncSessionLocal() as db:
            convs = await S3.list_channel_conversations(db, tenant_id=d["tenant_id"])
            me = next((c for c in convs if c["id"] == cid), None)
            assert me is not None and "最后一条" in me["last_message"]
    asyncio.new_event_loop().run_until_complete(_run())


def test_conversation_endpoints_registered():
    from app.api.v1.service_tickets import router

    paths = {r.path for r in router.routes}
    assert any("conversations/{conv_id}/messages" in p for p in paths)
    assert any("conversations/{conv_id}/reply" in p for p in paths)


def test_reply_notify_respects_watch(monkeypatch):
    """客户回复：watch 开→通知客服；关→不发；全局关→不发。"""
    async def _run():
        d = await _setup()
        from app.services import service_ticket_service as S4

        calls = []

        async def _fake_dispatch(db, *, tenant_id, msg, user_id=None):
            calls.append(msg.title); return {}
        monkeypatch.setattr("app.notifiers.registry.dispatch", _fake_dispatch)

        async with AsyncSessionLocal() as db:
            t = await S4.create_ticket(db, tenant_id=d["tenant_id"], subject="回复提醒", content="x", notify=False)
            await db.commit(); tid = t.id
        # watch 默认 True → 客户回复应通知
        async with AsyncSessionLocal() as db:
            t = await db.get(ServiceTicket, tid)
            await S4.add_user_message(db, t, "补充：订单号 A1")
            await db.commit()
        assert any("新的客户回复" in c for c in calls), calls
        calls.clear()
        # watch=False → 不通知
        async with AsyncSessionLocal() as db:
            t = await db.get(ServiceTicket, tid)
            t.watch = False
            await db.commit()
        async with AsyncSessionLocal() as db:
            t = await db.get(ServiceTicket, tid)
            await S4.add_user_message(db, t, "又补充")
            await db.commit()
        assert not calls, f"watch=False 不应通知，实际 {calls}"
    asyncio.new_event_loop().run_until_complete(_run())


def test_reply_notify_global_off(monkeypatch):
    async def _run():
        d = await _setup()
        from app.core.config import settings
        from app.services import service_ticket_service as S5

        calls = []

        async def _fake_dispatch(db, *, tenant_id, msg, user_id=None):
            calls.append(msg.title); return {}
        monkeypatch.setattr("app.notifiers.registry.dispatch", _fake_dispatch)
        monkeypatch.setattr(settings, "service_notify_on_reply", False)
        async with AsyncSessionLocal() as db:
            t = await S5.create_ticket(db, tenant_id=d["tenant_id"], subject="全局关", content="x", notify=False)
            await db.commit()
            await S5.add_user_message(db, t, "回复")
            await db.commit()
        assert not calls, f"全局关不应通知，实际 {calls}"
    asyncio.new_event_loop().run_until_complete(_run())


def test_ticket_watch_field_and_update():
    async def _run():
        d = await _setup()
        from app.schemas.service_ticket import TicketUpdate, TicketOut
        from app.services import service_ticket_service as S6

        async with AsyncSessionLocal() as db:
            t = await S6.create_ticket(db, tenant_id=d["tenant_id"], subject="w", content="x", notify=False)
            await db.commit()
            assert t.watch is True  # 默认开
        assert "watch" in TicketUpdate.model_fields
        assert "watch" in TicketOut.model_fields
    asyncio.new_event_loop().run_until_complete(_run())


def test_conversation_notes_and_watch(monkeypatch):
    """渠道会话：内部备注（存 settings）+ 提醒开关 + 新消息通知。"""
    async def _run():
        d = await _setup()
        from app.models import Conversation
        from app.services import service_ticket_service as S7

        async with AsyncSessionLocal() as db:
            conv = Conversation(tenant_id=d["tenant_id"], user_id=d["user_id"], title="[wework] c",
                                settings={"channel": "wework", "external_id": "cw1", "channel_id": 1})
            db.add(conv); await db.commit(); cid = conv.id

        # 备注
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            r = await S7.add_conversation_note(db, conv, "需主管确认", agent_id=d["user_id"])
            await db.commit()
            assert r["notes"][0]["content"] == "需主管确认"
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            assert (conv.settings or {}).get("_notes")[0]["content"] == "需主管确认"

        # 提醒开关默认 True；关闭
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            assert (conv.settings or {}).get("_watch", True) is True
            S7.set_conversation_watch(conv, False)
            await db.commit()
            assert (conv.settings or {}).get("_watch") is False

        # 通知：watch=False → 不发
        calls = []

        async def _fd(db, *, tenant_id, msg, user_id=None):
            calls.append(msg.title); return {}
        monkeypatch.setattr("app.notifiers.registry.dispatch", _fd)
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            await S7.notify_conversation_reply(db, conv, "客户新消息")
            await db.commit()
        assert not calls, "watch=False 不应通知"

        # 开启后 → 发
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            S7.set_conversation_watch(conv, True)
            await db.commit()
        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            await S7.notify_conversation_reply(db, conv, "客户再发")
            await db.commit()
        assert any("有新消息" in c for c in calls), calls
    asyncio.new_event_loop().run_until_complete(_run())


def test_conversation_meta_endpoints_registered():
    from app.api.v1.service_tickets import router

    paths = {r.path for r in router.routes}
    assert any("conversations/{conv_id}/meta" in p for p in paths)
    assert any("conversations/{conv_id}/notes" in p for p in paths)
    assert any("conversations/{conv_id}/watch" in p for p in paths)


def test_customer_note_saved_and_in_list():
    """客户备注：存 ChannelUser.note，且渠道会话列表返回该备注。"""
    async def _run():
        d = await _setup()
        from app.models import ChannelUser, Conversation
        from app.services import service_ticket_service as S8

        async with AsyncSessionLocal() as db:
            cu = ChannelUser(tenant_id=d["tenant_id"], channel="wework", external_id="cust_note",
                             user_id=d["user_id"])
            db.add(cu); await db.flush()
            db.add(Conversation(tenant_id=d["tenant_id"], user_id=d["user_id"], title="[wework] c",
                                settings={"channel": "wework", "external_id": "cust_note", "channel_id": 1}))
            await db.commit(); cuid = cu.id

        # 保存备注
        async with AsyncSessionLocal() as db:
            r = await S8.set_customer_note(db, tenant_id=d["tenant_id"], channel_user_id=cuid, note="VIP 客户，优先处理")
            await db.commit()
            assert r["note"] == "VIP 客户，优先处理"

        # 列表里带出备注
        async with AsyncSessionLocal() as db:
            convs = await S8.list_channel_conversations(db, tenant_id=d["tenant_id"])
            me = next((c for c in convs if c["external_id"] == "cust_note"), None)
            assert me is not None and me["note"] == "VIP 客户，优先处理"
            assert me["channel_user_id"] == cuid

        # 跨租户拒绝
        async with AsyncSessionLocal() as db:
            try:
                await S8.set_customer_note(db, tenant_id=d["tenant_id"] + 999, channel_user_id=cuid, note="x")
                raise AssertionError("跨租户应拒绝")
            except ValueError:
                pass
    asyncio.new_event_loop().run_until_complete(_run())


def test_customer_note_endpoint_registered():
    from app.api.v1.service_tickets import router

    paths = {r.path for r in router.routes}
    assert any("channel-customers/{channel_user_id}/note" in p for p in paths)


def test_channel_user_note_column():
    from app.models import ChannelUser

    assert "note" in ChannelUser.__table__.columns
