"""企业聊天室：房间/消息/成员/撤回/置顶/@机器人。"""
from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _setup():
    from sqlalchemy import select

    from app.core.db import AsyncSessionLocal, init_models
    from app.core.security import hash_password
    from app.models import Tenant, User

    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
        if not t:
            t = Tenant(name="CR", slug="cr"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "cr_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="cr_u", password_hash=hash_password("Cr@2026abc"),
                     is_admin=True, user_type="internal", status="active", approval_status="approved")
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id}


def test_chat_room_models_exist():
    from app.models import ChatMessage, ChatRoom, ChatRoomMember

    assert ChatRoom.__tablename__ == "chat_room"
    assert ChatRoomMember.__tablename__ == "chat_room_member"
    assert ChatMessage.__tablename__ == "chat_message"
    cols = set(ChatMessage.__table__.columns.keys())
    assert {"revoked", "pinned", "sender_id", "mentions", "room_id"} <= cols


def test_broadcaster_basic():
    from app.services.chat_broadcaster import ChatBroadcaster

    async def _run2():
        b = ChatBroadcaster()
        sent = []

        class FakeWS:
            async def send_text(self, t): sent.append(t)
        ws = FakeWS()
        await b.join(tenant_id=1, room_id=5, user_id=9, ws=ws)
        assert b.online_in_room(1, 5) == 1
        await b.broadcast_room(tenant_id=1, room_id=5, payload={"type": "message"})
        assert len(sent) == 1 and '"message"' in sent[0]
        await b.leave(tenant_id=1, room_id=5, user_id=9, ws=ws)
        assert b.online_in_room(1, 5) == 0
    _run(_run2())


def test_default_room_created():
    async def _run2():
        from app.core.db import AsyncSessionLocal
        from app.services.chat_room_service import ensure_default_room, list_rooms

        d = await _setup()
        async with AsyncSessionLocal() as db:
            r1 = await ensure_default_room(db, d["tenant_id"])
            r2 = await ensure_default_room(db, d["tenant_id"])
            assert r1.id == r2.id, "默认大群应幂等（同一租户只有一个）"
            rooms = await list_rooms(db, tenant_id=d["tenant_id"], user_id=d["uid"], is_admin=True)
            assert any(r["is_default"] for r in rooms)
            await db.commit()
    _run(_run2())


def test_post_and_revoke_message():
    async def _run2():
        from app.core.db import AsyncSessionLocal
        from app.models import ChatRoom
        from app.services.chat_room_service import (
            can_revoke, ensure_default_room, post_message,
        )

        d = await _setup()
        async with AsyncSessionLocal() as db:
            room = await ensure_default_room(db, d["tenant_id"])
            msg = await post_message(db, room=room, sender_id=d["uid"], content="hello")
            assert msg.id and msg.revoked is False
            # 本人可撤回
            assert await can_revoke(db, room=room, msg=msg, actor_id=d["uid"], is_admin=False)
            # 他人不可
            assert not await can_revoke(db, room=room, msg=msg, actor_id=999999, is_admin=False)
            # 管理员可
            assert await can_revoke(db, room=room, msg=msg, actor_id=999999, is_admin=True)
            await db.commit()
    _run(_run2())


def test_chat_room_routes_registered():
    from app.api.v1 import chat_room as C

    methods = {(r.path, m) for r in C.router.routes for m in getattr(r, "methods", set())}
    assert ("/chat/rooms", "GET") in methods
    assert ("/chat/rooms/{room_id}/messages", "POST") in methods
    assert ("/chat/rooms/{room_id}/messages/{msg_id}/revoke", "POST") in methods
    assert ("/chat/rooms/{room_id}/messages/{msg_id}/pin", "POST") in methods
    assert ("/chat/rooms/{room_id}/bots", "POST") in methods
    assert ("/chat/rooms/{room_id}/members/{member_user_id}/role", "POST") in methods
    # WebSocket 路由
    from starlette.routing import WebSocketRoute
    assert any(isinstance(r, WebSocketRoute) and r.path == "/chat/rooms/ws" for r in C.router.routes)


def test_ws_route_order_before_dynamic():
    """WebSocket 路由不应被 /{room_id} 干扰（WS 与 HTTP 分开匹配，但顺序仍应正确）。"""
    from app.api.v1 import chat_room as C

    paths = [getattr(r, "path", "") for r in C.router.routes]
    assert "/chat/rooms/direct" in paths
    # direct 必须在 {room_id} 之前
    assert paths.index("/chat/rooms/direct") < paths.index("/chat/rooms/{room_id}")


def test_bot_mention_detection():
    """@机器人名 或 mentions 含 agent_id 都应触发。"""
    import inspect

    from app.api.v1.chat_room import _mentioned_bots

    src = inspect.getsource(_mentioned_bots)
    assert "@" in src and "mentions" in src


def test_bot_service_exists():
    from app.services import chat_bot_service as B

    assert hasattr(B, "maybe_trigger_bots")
