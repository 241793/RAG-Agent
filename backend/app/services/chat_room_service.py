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


async def get_member_row(db: AsyncSession, *, room_id: int, user_id: int) -> ChatRoomMember | None:
    """只取库中真实成员行（默认大群的「虚拟成员」返回 None）。"""
    return (
        await db.execute(
            select(ChatRoomMember).where(
                ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def ensure_member_row(
    db: AsyncSession, *, tenant_id: int, room_id: int, user_id: int, role: str = "member",
) -> ChatRoomMember:
    """取库中成员行，不存在则落库（用于对默认大群虚拟成员执行禁言/设管理员等持久化操作）。"""
    m = await get_member_row(db, room_id=room_id, user_id=user_id)
    if not m:
        m = ChatRoomMember(tenant_id=tenant_id, room_id=room_id, user_id=user_id, role=role)
        db.add(m)
        await db.flush()
    return m


async def mark_read(db: AsyncSession, *, room_id: int, user_id: int, tenant_id: int) -> None:
    """记录已读水位（毫秒）。

    默认大群成员可能是「虚拟成员」（未显式入表），此处确保持久化一条成员行，
    否则 last_read_at 写入内存对象、会话结束即丢失，导致未读数永远不清零。
    """
    m = await ensure_member_row(db, tenant_id=tenant_id, room_id=room_id, user_id=user_id)
    m.last_read_at = _now_ms()
    await db.flush()


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
    """把消息序列化成前端结构（含发送者名/用户名/部门/头像，撤回占位）。"""
    nm = name_map or {}
    sender = nm.get(msg.sender_id or 0, {}) if msg.sender_type == "user" else {}
    if msg.sender_type == "agent":
        ag = await db.get(Agent, msg.sender_id) if msg.sender_id else None
        sender = {"name": (ag.name if ag else "机器人"), "is_agent": True, "agent_id": msg.sender_id}
    return {
        "id": msg.id, "room_id": msg.room_id, "sender_id": msg.sender_id,
        "sender_type": msg.sender_type, "sender_name": sender.get("name") or "未知",
        "sender_username": sender.get("username"),
        "sender_department": sender.get("department"),
        "sender_is_agent": bool(sender.get("is_agent")),
        "content": "" if msg.revoked else msg.content,
        "content_type": msg.content_type,
        "attachments": None if msg.revoked else msg.attachments,
        "mentions": msg.mentions, "reply_to_id": msg.reply_to_id,
        "pinned": msg.pinned, "revoked": msg.revoked, "revoked_by": msg.revoked_by,
        "created_at": msg.created_at,
    }


async def name_map_for(db: AsyncSession, msgs: list[ChatMessage]) -> dict[int, dict]:
    """构造 {user_id: {name, username, department}} 映射（用于消息序列化）。"""
    from app.models import Department

    ids = [m.sender_id for m in msgs if m.sender_type == "user" and m.sender_id]
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(set(ids))))).scalars().all()
    dept_ids = {u.department_id for u in rows if u.department_id}
    dept_map: dict[int, str] = {}
    if dept_ids:
        depts = (await db.execute(select(Department).where(Department.id.in_(dept_ids)))).scalars().all()
        dept_map = {d.id: d.name for d in depts}
    return {
        u.id: {
            "name": u.display_name or u.username,
            "username": u.username,
            "department": dept_map.get(u.department_id) if u.department_id else None,
        }
        for u in rows
    }


async def search_messages(
    db: AsyncSession, *, room_id: int, keyword: str, limit: int = 30,
    before_id: int | None = None,
) -> list[ChatMessage]:
    """按关键词搜索群内历史消息（撤回的除外，内容/附件名匹配）。"""
    kw = (keyword or "").strip()
    stmt = select(ChatMessage).where(
        ChatMessage.room_id == room_id,
        ChatMessage.revoked.is_(False),
        ChatMessage.content.ilike(f"%{kw}%") if kw else True,
    )
    if before_id:
        stmt = stmt.where(ChatMessage.id < before_id)
    stmt = stmt.order_by(ChatMessage.id.desc()).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


async def room_stats(db: AsyncSession, *, room: ChatRoom, days: int = 7) -> dict:
    """群活跃统计：成员数/消息总数/最近 N 天消息数/活跃人数/Top 发言者/近期要点。"""
    from app.services.chat_room_service import _now_ms as _now

    now_ms = _now()
    since = now_ms - days * 86_400_000

    member_count = int(
        (await db.execute(
            select(func.count()).select_from(ChatRoomMember).where(ChatRoomMember.room_id == room.id)
        )).scalar_one()
    )
    message_count = int(room.message_count or 0)
    recent_rows = (
        await db.execute(
            select(ChatMessage).where(
                ChatMessage.room_id == room.id,
                ChatMessage.revoked.is_(False),
                ChatMessage.created_at >= since,
            ).order_by(ChatMessage.id.desc())
        )
    ).scalars().all()
    recent_count = len(recent_rows)
    speakers: dict[int, int] = {}
    for m in recent_rows:
        if m.sender_type == "user" and m.sender_id:
            speakers[m.sender_id] = speakers.get(m.sender_id, 0) + 1
    nm = await name_map_for(db, list(recent_rows))
    top = sorted(speakers.items(), key=lambda x: -x[1])[:5]
    top_speakers = [(nm.get(uid, {}).get("name") or f"用户{uid}", c) for uid, c in top]
    # 近期代表消息（最近 8 条有内容的）
    snippets = [m.content[:80] for m in recent_rows if m.content][:8]
    return {
        "member_count": member_count,
        "message_count": message_count,
        "recent_count": recent_count,
        "active_users": len(speakers),
        "speakers": speakers,
        "top_speakers": top_speakers,
        "recent_snippets": snippets,
    }


async def set_mute_all(
    db: AsyncSession, *, room: ChatRoom, enabled: bool, minutes: int = 0,
) -> int | None:
    """开启/关闭全员禁言。存入 room.settings["mute_all_until"]（毫秒，None=未开启）。

    开启时可带 minutes（到点自动解除由调度器/读取时判断）。返回该到期时刻。
    """
    settings_ = dict(room.settings or {})
    if enabled:
        until = _now_ms() + minutes * 60_000 if minutes > 0 else 0
        settings_["mute_all_until"] = until
        room.settings = settings_
    else:
        settings_.pop("mute_all_until", None)
        room.settings = settings_
    await db.flush()
    return settings_.get("mute_all_until")


def mute_all_active(room: ChatRoom) -> bool:
    """全员禁言是否生效（0 表示手动解除前一直生效）。"""
    until = (room.settings or {}).get("mute_all_until")
    if until is None:
        return False
    if until == 0:
        return True
    return until > _now_ms()
