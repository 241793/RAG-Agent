"""聊天室业务逻辑：房间/成员/消息、默认大群、成员角色、撤回/置顶。"""
from __future__ import annotations

import time

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.models import Agent, ChatMessage, ChatRoom, ChatRoomMember, User

logger = get_logger("chat_room")

DEFAULT_ROOM_NAME = "全员大群"


def _now_ms() -> int:
    return int(time.time() * 1000)


async def ensure_default_room(db: AsyncSession, tenant_id: int) -> ChatRoom:
    """确保租户有「全员大群」，返回它（幂等）。"""
    room = (
        await db.execute(
            select(ChatRoom).where(
                ChatRoom.tenant_id == tenant_id, ChatRoom.is_default.is_(True),
                ChatRoom.status == "active",
            )
        )
    ).scalars().first()
    if room:
        return room
    # 用第一个管理员作为群主
    owner = (
        await db.execute(
            select(User).where(User.tenant_id == tenant_id, User.is_admin.is_(True))
            .order_by(User.id)
        )
    ).scalars().first()
    room = ChatRoom(
        tenant_id=tenant_id, name=DEFAULT_ROOM_NAME, kind="group",
        owner_id=owner.id if owner else 0, is_default=True,
        announcement="欢迎使用企业聊天室。请文明发言，涉及敏感信息请注意合规。",
    )
    db.add(room)
    await db.flush()
    if owner:
        db.add(ChatRoomMember(
            tenant_id=tenant_id, room_id=room.id, user_id=owner.id, role="owner",
        ))
        await db.flush()
    logger.info("default_room_created", tenant_id=tenant_id, room_id=room.id)
    return room


async def is_member(db: AsyncSession, *, room_id: int, user_id: int) -> ChatRoomMember | None:
    """是否为成员。默认大群：所有内部用户天然是成员（动态，不依赖成员表）。

    非默认群仍以成员表为准。
    """
    m = (
        await db.execute(
            select(ChatRoomMember).where(
                ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if m:
        return m
    # 默认大群：任何内部用户视为成员（构造一个内存对象，不落库）
    room = await db.get(ChatRoom, room_id)
    if room and room.is_default and room.tenant_id:
        u = await db.get(User, user_id)
        if u and u.tenant_id == room.tenant_id and getattr(u, "user_type", "internal") != "external":
            return ChatRoomMember(room_id=room_id, user_id=user_id, role="member")
    return None


async def member_role(db: AsyncSession, *, room: ChatRoom, user_id: int, is_admin: bool) -> str:
    """有效角色：租户管理员在群里等同 owner（拥有撤回任何消息等权力）。"""
    if is_admin or room.owner_id == user_id:
        return "owner"
    m = await is_member(db, room_id=room.id, user_id=user_id)
    return m.role if m else ""


async def can_access(db: AsyncSession, *, room: ChatRoom, user_id: int, is_admin: bool) -> bool:
    """能否查看房间：默认大群全员可见；其它群需是成员；管理员均可。"""
    if is_admin or room.is_default or room.owner_id == user_id:
        return True
    return (await is_member(db, room_id=room.id, user_id=user_id)) is not None


async def list_rooms(db: AsyncSession, *, tenant_id: int, user_id: int, is_admin: bool) -> list[dict]:
    """我可见的房间：默认大群 + 我加入的群 + 我的私聊。附未读数与最后一条消息摘要。"""
    await ensure_default_room(db, tenant_id)
    # 我加入的 room_id
    my_rooms = [
        r for (r,) in (await db.execute(
            select(ChatRoomMember.room_id).where(ChatRoomMember.user_id == user_id)
        )).all()
    ]
    stmt = select(ChatRoom).where(
        ChatRoom.tenant_id == tenant_id,
        ChatRoom.status == "active",
        or_(
            ChatRoom.is_default.is_(True),
            ChatRoom.id.in_(my_rooms or [-1]),
            ChatRoom.owner_id == user_id,
        ),
    ).order_by(ChatRoom.last_message_at.desc().nullslast(), ChatRoom.id.desc())
    rooms = (await db.execute(stmt)).scalars().all()

    out: list[dict] = []
    for room in rooms:
        last = (
            await db.execute(
                select(ChatMessage).where(ChatMessage.room_id == room.id)
                .order_by(ChatMessage.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        m = await is_member(db, room_id=room.id, user_id=user_id)
        last_read = (m.last_read_at if m else None) or 0
        unread = (
            await db.execute(
                select(func.count()).select_from(ChatMessage).where(
                    ChatMessage.room_id == room.id, ChatMessage.created_at > last_read,
                    ChatMessage.revoked.is_(False),
                )
            )
        ).scalar_one()
        out.append(_room_brief(room, last=last, unread=int(unread), my_role=(m.role if m else ("owner" if room.owner_id == user_id else ""))))
    return out


def _room_brief(room: ChatRoom, *, last: ChatMessage | None, unread: int, my_role: str) -> dict:
    preview = ""
    if last:
        if last.revoked:
            preview = "（消息已撤回）"
        elif last.content:
            preview = last.content[:60]
        elif last.attachments:
            preview = "[附件]"
    return {
        "id": room.id, "name": room.name, "kind": room.kind, "is_default": room.is_default,
        "announcement": room.announcement, "owner_id": room.owner_id, "my_role": my_role,
        "peer_user_id": room.peer_user_id,
        "last_message_at": room.last_message_at, "last_preview": preview,
        "message_count": room.message_count, "unread": unread,
    }


async def get_or_create_direct(db: AsyncSession, *, tenant_id: int, user_id: int, peer_id: int) -> ChatRoom:
    """私聊房间：按无序 user 对唯一。"""
    if user_id == peer_id:
        raise ConflictError("不能与自己私聊")
    a, b = sorted((user_id, peer_id))
    room = (
        await db.execute(
            select(ChatRoom).where(
                ChatRoom.tenant_id == tenant_id, ChatRoom.kind == "direct",
                ChatRoom.owner_id == a, ChatRoom.peer_user_id == b, ChatRoom.status == "active",
            )
        )
    ).scalars().first()
    if room:
        return room
    peer = await db.get(User, peer_id)
    if not peer or peer.tenant_id != tenant_id:
        raise NotFoundError("对方用户不存在")
    room = ChatRoom(
        tenant_id=tenant_id, name="私聊", kind="direct",
        owner_id=a, peer_user_id=b,
    )
    db.add(room)
    await db.flush()
    db.add_all([
        ChatRoomMember(tenant_id=tenant_id, room_id=room.id, user_id=a, role="member"),
        ChatRoomMember(tenant_id=tenant_id, room_id=room.id, user_id=b, role="member"),
    ])
    await db.flush()
    return room


async def post_message(
    db: AsyncSession, *, room: ChatRoom, sender_id: int | None, sender_type: str = "user",
    content: str = "", attachments: list | None = None, mentions: list | None = None,
    reply_to_id: int | None = None, content_type: str = "text",
) -> ChatMessage:
    """落一条消息并更新房间摘要计数。"""
    msg = ChatMessage(
        tenant_id=room.tenant_id, room_id=room.id, sender_id=sender_id,
        sender_type=sender_type, content=content, content_type=content_type,
        attachments=attachments or None, mentions=mentions or None,
        reply_to_id=reply_to_id, created_at=_now_ms(),
    )
    db.add(msg)
    room.last_message_at = msg.created_at
    room.message_count = (room.message_count or 0) + 1
    await db.flush()
    return msg


async def can_revoke(db: AsyncSession, *, room: ChatRoom, msg: ChatMessage, actor_id: int, is_admin: bool) -> bool:
    """撤回权限：本人 或 群主/群管理员/租户管理员。"""
    if is_admin or room.owner_id == actor_id:
        return True
    role = await member_role(db, room=room, user_id=actor_id, is_admin=is_admin)
    if role in ("owner", "admin"):
        return True
    return msg.sender_id == actor_id and msg.sender_type == "user"


async def serialize_message(db: AsyncSession, msg: ChatMessage, *, name_map: dict[int, dict] | None = None) -> dict:
    """把消息序列化成前端结构（含发送者名/头像，撤回占位）。"""
    nm = name_map or {}
    sender = nm.get(msg.sender_id or 0, {}) if msg.sender_type == "user" else {}
    if msg.sender_type == "agent":
        ag = await db.get(Agent, msg.sender_id) if msg.sender_id else None
        sender = {"name": (ag.name if ag else "机器人"), "is_agent": True, "agent_id": msg.sender_id}
    return {
        "id": msg.id, "room_id": msg.room_id, "sender_id": msg.sender_id,
        "sender_type": msg.sender_type, "sender_name": sender.get("name") or "未知",
        "sender_is_agent": bool(sender.get("is_agent")),
        "content": "" if msg.revoked else msg.content,
        "content_type": msg.content_type,
        "attachments": None if msg.revoked else msg.attachments,
        "mentions": msg.mentions, "reply_to_id": msg.reply_to_id,
        "pinned": msg.pinned, "revoked": msg.revoked, "revoked_by": msg.revoked_by,
        "created_at": msg.created_at,
    }


async def name_map_for(db: AsyncSession, msgs: list[ChatMessage]) -> dict[int, dict]:
    ids = [m.sender_id for m in msgs if m.sender_type == "user" and m.sender_id]
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(set(ids))))).scalars().all()
    return {u.id: {"name": u.display_name or u.username, "username": u.username} for u in rows}
