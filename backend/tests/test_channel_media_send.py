"""客服发送附件：会话内发附件落库+回发；各渠道 media 处理。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.channels.base import OutboundMessage
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Channel, Conversation, Tenant, User
from app.services import service_ticket_service as S


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "cms"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="CMS", slug="cms"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "cms_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="cms_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        ch = (await db.execute(select(Channel).where(Channel.name == "cms_ch"))).scalar_one_or_none()
        if not ch:
            ch = Channel(tenant_id=t.id, kind="feishu", name="cms_ch", enabled=True); db.add(ch); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id, "channel_id": ch.id}


def test_send_attachment_falls_back_and_stores(monkeypatch):
    """客服发附件：落 agent 附件消息；mock 渠道回发。"""
    async def _run():
        d = await _setup()
        from app.ingest.storage import get_storage
        file_key, _ = get_storage().save(tenant_id=d["tenant_id"], filename="说明.png", data=b"PNGDATA")

        async with AsyncSessionLocal() as db:
            conv = Conversation(
                tenant_id=d["tenant_id"], user_id=d["user_id"], title="[feishu] 客户",
                settings={"channel": "feishu", "external_id": "fs1", "channel_id": d["channel_id"]},
            )
            db.add(conv); await db.commit(); cid = conv.id

        captured = []
        from app.channels.manager import channel_manager

        async def _fake_send(channel_id, kind, out):
            captured.append(out); return True
        monkeypatch.setattr(channel_manager, "send_with_fallback", _fake_send)

        async with AsyncSessionLocal() as db:
            conv = await db.get(Conversation, cid)
            r = await S.send_attachment_in_conversation(
                db, conversation=conv, agent_id=d["user_id"], file_key=file_key,
                name="说明.png", mime="image/png", size=7, kind="image")
            await db.commit()
            assert r["ok"] and r["sent_to_channel"] is True
            assert r["attachment"]["file_key"] == file_key
        # 校验：out 的 media 非空且是 image
        assert captured and captured[0].media
        assert captured[0].media[0]["type"] == "image"
        # 会话里落了 agent 附件消息
        async with AsyncSessionLocal() as db:
            msgs = await S.conversation_messages(db, conversation_id=cid, tenant_id=d["tenant_id"])
            assert any(m["role"] == "agent" and m["attachments"] for m in msgs)
    asyncio.new_event_loop().run_until_complete(_run())


def test_wework_appends_attachment_name():
    """企微不支持主动发图 → 文本兜底含 [附件] 文件名。"""
    from app.channels.drivers.wework import WeWorkAdapter

    a = WeWorkAdapter.__new__(WeWorkAdapter)
    a.cfg = {}; a._req_ids = {}
    # 直接测文本拼装（不动 websocket）
    import types
    sent = {}

    class FakeWS:
        async def send(self, s): sent["data"] = s
    a._ws = FakeWS()
    a._req_ids = {}

    async def _run():
        ok = await a.send_message(OutboundMessage(content="您好", user_id="u1", media=[{"type": "image", "name": "图.png"}]))
        assert ok is True
        import json as _j
        content = _j.loads(sent["data"])["body"]["markdown"]["content"]
        assert "图.png" in content and "[附件]" in content
    asyncio.new_event_loop().run_until_complete(_run())


def test_qqbot_appends_attachment_name(monkeypatch):
    from app.channels.drivers.qqbot import QQBotAdapter

    a = QQBotAdapter.__new__(QQBotAdapter)
    a._sessions = {}
    captured = {}
    from app.channels.base import OutboundMessage as OM

    async def _fake_api(method, path, body=None):
        captured["body"] = body; return {"code": 0}
    a._api = _fake_api

    async def _run():
        ok = await a.send_message(OM(content="hi", user_id="u1", media=[{"type": "file", "name": "合同.pdf"}]))
        assert ok is True and "合同.pdf" in captured["body"]["content"]
    asyncio.new_event_loop().run_until_complete(_run())


def test_feishu_send_media_method_exists():
    from app.channels.drivers.feishu import FeishuAdapter

    assert hasattr(FeishuAdapter, "_send_media")


def test_attachment_endpoint_registered():
    from app.api.v1.service_tickets import router

    paths = {r.path for r in router.routes}
    assert any("conversations/{conv_id}/attachment" in p for p in paths)
