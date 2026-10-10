"""企业聊天室接口：房间/消息/成员 + WebSocket 实时推送。

- REST 负责：拉房间列表、历史消息（分页）、发消息、撤回、置顶、成员管理、加机器人。
- WebSocket `/chat/rooms/ws?token=` 负责：实时接收该用户可见房间的新消息/撤回/置顶事件。
  鉴权用 query 里的 access token（浏览器原生 WS 无法带 Authorization 头）。
"""
from __future__ import annotations

import time

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal, get_db
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.middleware.auth_dep import get_current_user, require_permission
from app.models import ChatMessage, ChatRoom, ChatRoomMember, User
from app.services import chat_room_service as S
from app.services.audit_service import audited
from app.services.chat_broadcaster import broadcaster

router = APIRouter(prefix="/chat/rooms", tags=["chat_room"])


def _now_ms() -> int:
    return int(time.time() * 1000)


# ==================== 房间 ====================
@router.get("")
async def list_rooms(
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """我可见的房间（默认大群 + 我加入的群 + 我的私聊），带未读数。"""
    return await S.list_rooms(db, tenant_id=user.tenant_id, user_id=user.id, is_admin=bool(user.is_admin))


@router.post("")
@audited("chat_room.create", "chat_room")
async def create_room(
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建群聊。"""
    name = (body.get("name") or "").strip()
    if not name:
        raise ValidationError("请填写群名称")
    room = ChatRoom(
        tenant_id=user.tenant_id, name=name[:128], kind="group",
        owner_id=user.id, announcement=(body.get("announcement") or None),
    )
    db.add(room)
    await db.flush()
    db.add(ChatRoomMember(tenant_id=user.tenant_id, room_id=room.id, user_id=user.id, role="owner"))
    # 创建者指定初始成员
    for uid in (body.get("member_ids") or []):
        if int(uid) == user.id:
            continue
        db.add(ChatRoomMember(tenant_id=user.tenant_id, room_id=room.id, user_id=int(uid), role="member", added_by=user.id))
    await db.flush()
    return {"id": room.id, "name": room.name, "message": "已创建"}


@router.post("/direct")
async def create_direct(
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """开启/复用与某人的私聊。"""
    peer = int(body.get("user_id") or 0)
    room = await S.get_or_create_direct(db, tenant_id=user.tenant_id, user_id=user.id, peer_id=peer)
    await db.flush()
    return {"id": room.id, "kind": "direct", "message": "ok"}


@router.get("/{room_id}")
async def room_detail(
    room_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    room = await db.get(ChatRoom, room_id)
    if not room or room.tenant_id != user.tenant_id:
        raise NotFoundError("房间不存在")
    if not await S.can_access(db, room=room, user_id=user.id, is_admin=bool(user.is_admin)):
        raise PermissionDeniedError("你不是该聊天成员")
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    # 成员列表
    members = await _room_members(db, room)
    bots = await _room_bots(db, room)
    pinned = (
        await db.execute(
            select(ChatMessage).where(ChatMessage.room_id == room_id, ChatMessage.pinned.is_(True), ChatMessage.revoked.is_(False))
            .order_by(ChatMessage.id.desc()).limit(20)
        )
    ).scalars().all()
    nm = await S.name_map_for(db, list(pinned))
    return {
        "id": room.id, "name": room.name, "kind": room.kind, "is_default": room.is_default,
        "announcement": room.announcement, "owner_id": room.owner_id, "my_role": role,
        "peer_user_id": room.peer_user_id, "members": members, "bots": bots,
        "pinned": [await S.serialize_message(db, m, name_map=nm) for m in pinned],
    }


async def _room_members(db: AsyncSession, room: ChatRoom) -> list[dict]:
    """成员列表。默认大群 = 全部内部用户（动态），其余群 = 成员表。

    角色来自成员表（默认大群里未显式入表的用户视为普通成员）。
    """
    # 成员表中的角色覆盖
    rows = (
        await db.execute(select(ChatRoomMember).where(ChatRoomMember.room_id == room.id))
    ).scalars().all()
    role_map: dict[int, str] = {}
    for m in rows:
        if m.user_id:
            role_map[m.user_id] = m.role

    if room.is_default:
        # 全员：本租户全部内部用户
        users = (
            await db.execute(
                select(User).where(
                    User.tenant_id == room.tenant_id,
                    or_(User.user_type.is_(None), User.user_type != "external"),
                    or_(User.status.is_(None), User.status == "active"),
                ).order_by(User.id)
            )
        ).scalars().all()
    else:
        uids = [m.user_id for m in rows if m.user_id]
        users = (
            (await db.execute(select(User).where(User.id.in_(set(uids))))).scalars().all()
            if uids else []
        )
    out = []
    for u in users:
        role = role_map.get(u.id, "member")
        if room.owner_id == u.id:
            role = "owner"
        out.append({
            "id": u.id, "user_id": u.id, "role": role,
            "name": u.display_name or u.username, "username": u.username,
            "is_admin": bool(u.is_admin),
            "muted_until": next((m.muted_until for m in rows if m.user_id == u.id), None),
        })
    return out


async def _room_bots(db: AsyncSession, room: ChatRoom) -> list[dict]:
    from app.models import Agent

    rows = (
        await db.execute(
            select(ChatRoomMember).where(ChatRoomMember.room_id == room.id, ChatRoomMember.agent_id.is_not(None))
        )
    ).scalars().all()
    out = []
    for m in rows:
        ag = await db.get(Agent, m.agent_id)
        out.append({"member_id": m.id, "agent_id": m.agent_id, "name": ag.name if ag else f"机器人#{m.agent_id}"})
    return out


# ==================== 消息 ====================
@router.get("/{room_id}/messages")
async def list_messages(
    room_id: int,
    before_id: int | None = Query(None, description="拉取此消息 id 之前的历史（分页）"),
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    room = await _guard_room(db, user, room_id)
    stmt = select(ChatMessage).where(ChatMessage.room_id == room_id)
    if before_id:
        stmt = stmt.where(ChatMessage.id < before_id)
    stmt = stmt.order_by(ChatMessage.id.desc()).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()  # 返回按时间正序，便于前端直接 append
    nm = await S.name_map_for(db, rows)
    items = [await S.serialize_message(db, m, name_map=nm) for m in rows]
    # 标记已读
    m = await S.is_member(db, room_id=room_id, user_id=user.id)
    if m:
        m.last_read_at = _now_ms()
        await db.flush()
    return {"items": items, "has_more": len(rows) == limit}


@router.post("/{room_id}/messages")
@audited("chat_room.message", "chat_room")
async def send_message(
    room_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发消息（支持附件/@提及/引用回复）。"""
    room = await _guard_room(db, user, room_id)
    # 禁言检查
    m = await S.is_member(db, room_id=room_id, user_id=user.id)
    if m and m.muted_until and m.muted_until > _now_ms():
        raise PermissionDeniedError("你已被禁言")
    content = (body.get("content") or "").strip()
    attachments = body.get("attachments") or None
    if not content and not attachments:
        raise ValidationError("消息不能为空")
    mentions = [int(x) for x in (body.get("mentions") or [])]
    msg = await S.post_message(
        db, room=room, sender_id=user.id, sender_type="user",
        content=content, attachments=attachments, mentions=mentions,
        reply_to_id=body.get("reply_to_id"),
    )
    await db.flush()
    nm = await S.name_map_for(db, [msg])
    out = await S.serialize_message(db, msg, name_map=nm)
    # 实时广播
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "message", "room_id": room.id, "message": out})
    # @机器人：被 @ 的机器人异步回复
    from app.services.chat_bot_service import maybe_trigger_bots

    bot_ids = await _mentioned_bots(db, room, mentions, content)
    if bot_ids:
        import asyncio

        for bid in bot_ids:
            asyncio.create_task(maybe_trigger_bots(room.id, bid, content, user.id))
    return out


async def _mentioned_bots(db: AsyncSession, room: ChatRoom, mentions: list[int], content: str) -> list[int]:
    """找出需要响应的机器人：要么显式 @（mentions 里带其 Agent id），要么内容含 @机器人名。"""
    bots = (
        await db.execute(
            select(ChatRoomMember.agent_id).where(
                ChatRoomMember.room_id == room.id, ChatRoomMember.agent_id.is_not(None)
            )
        )
    ).all()
    bot_ids = [b[0] for b in bots if b[0]]
    if not bot_ids:
        return []
    from app.models import Agent

    hit = []
    for bid in bot_ids:
        if bid in mentions:
            hit.append(bid)
            continue
        ag = await db.get(Agent, bid)
        if ag and f"@{ag.name}" in (content or ""):
            hit.append(bid)
    return hit


@router.get("/{room_id}/files")
async def list_files(
    room_id: int,
    kind: str | None = Query(None, description="image / video / audio / file，留空=全部"),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """群文件/相册：汇总本群所有带附件的消息（撤回的除外）。"""
    room = await _guard_room(db, user, room_id)
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.room_id == room.id,
            ChatMessage.revoked.is_(False),
            ChatMessage.attachments.is_not(None),
        )
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    nm = await S.name_map_for(db, rows)
    out: list[dict] = []
    for m in rows:
        sender = nm.get(m.sender_id or 0, {})
        for att in (m.attachments or []):
            ctype = (att.get("type") or att.get("mime") or "file").lower()
            cat = _attach_category(ctype, att.get("name") or "")
            if kind and cat != kind:
                continue
            out.append({
                "message_id": m.id, "created_at": m.created_at,
                "sender_name": sender.get("name") or "未知",
                "category": cat,
                "name": att.get("name") or "附件",
                "att": att,
            })
    return out


def _attach_category(content_type: str, name: str = "") -> str:
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    # 回退按扩展名判断
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"):
        return "image"
    if ext in ("mp4", "webm", "mov", "avi", "mkv"):
        return "video"
    if ext in ("mp3", "wav", "ogg", "m4a", "flac", "aac"):
        return "audio"
    return "file"


@router.post("/{room_id}/messages/{msg_id}/revoke")
async def revoke_message(
    room_id: int,
    msg_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """撤回消息：本人 / 群管理员 / 群主 / 租户管理员。"""
    room = await _guard_room(db, user, room_id)
    msg = await db.get(ChatMessage, msg_id)
    if not msg or msg.room_id != room_id:
        raise NotFoundError("消息不存在")
    if not await S.can_revoke(db, room=room, msg=msg, actor_id=user.id, is_admin=bool(user.is_admin)):
        raise PermissionDeniedError("无权撤回该消息（仅本人或群管理员可撤回）")
    msg.revoked = True
    msg.revoked_by = user.id
    msg.revoked_at = _now_ms()
    msg.content = ""
    msg.attachments = None
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "revoke", "room_id": room.id, "message_id": msg_id, "revoked_by": user.id})
    return {"message": "已撤回"}


@router.post("/{room_id}/messages/{msg_id}/pin")
async def pin_message(
    room_id: int,
    msg_id: int,
    body: dict | None = None,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """置顶/取消置顶消息（群管理员以上）。"""
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    if role not in ("owner", "admin"):
        raise PermissionDeniedError("仅群管理员可置顶消息")
    msg = await db.get(ChatMessage, msg_id)
    if not msg or msg.room_id != room_id:
        raise NotFoundError("消息不存在")
    pinned = True if body is None else bool((body or {}).get("pinned", True))
    msg.pinned = pinned
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "pin", "room_id": room.id, "message_id": msg_id, "pinned": pinned})
    return {"message": "已置顶" if pinned else "已取消置顶"}


@router.post("/{room_id}/read")
async def mark_read(
    room_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _guard_room(db, user, room_id)
    m = await S.is_member(db, room_id=room_id, user_id=user.id)
    if m:
        m.last_read_at = _now_ms()
        await db.flush()
    return {"message": "ok"}


# ==================== 成员/管理 ====================
def _require_admin_role(role: str) -> None:
    if role not in ("owner", "admin"):
        raise PermissionDeniedError("仅群主/群管理员可执行该操作")


@router.post("/{room_id}/members")
async def add_members(
    room_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """拉人入群（成员即可拉人；管理员以上可设置管理员）。"""
    room = await _guard_room(db, user, room_id)
    added = 0
    for uid in (body.get("user_ids") or []):
        uid = int(uid)
        if await S.is_member(db, room_id=room_id, user_id=uid):
            continue
        db.add(ChatRoomMember(tenant_id=room.tenant_id, room_id=room_id, user_id=uid, role="member", added_by=user.id))
        added += 1
    await db.flush()
    return {"message": f"已添加 {added} 人", "count": added}


@router.post("/{room_id}/members/{member_user_id}/role")
async def set_member_role(
    room_id: int,
    member_user_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """设置/取消群管理员（仅群主）。"""
    room = await _guard_room(db, user, room_id)
    if room.owner_id != user.id and not user.is_admin:
        raise PermissionDeniedError("仅群主可设置群管理员")
    role = (body.get("role") or "member")
    if role not in ("admin", "member"):
        raise ValidationError("role 只能为 admin/member")
    m = await S.is_member(db, room_id=room_id, user_id=member_user_id)
    if not m:
        raise NotFoundError("该用户不在群里")
    m.role = role
    await db.flush()
    return {"message": "已设为群管理员" if role == "admin" else "已取消群管理员"}


@router.delete("/{room_id}/members/{member_user_id}")
async def remove_member(
    room_id: int,
    member_user_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """移除成员（管理员以上）。"""
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    if member_user_id == room.owner_id:
        raise PermissionDeniedError("不能移除群主")
    m = await S.is_member(db, room_id=room_id, user_id=member_user_id)
    if m:
        await db.delete(m)
        await db.flush()
    return {"message": "已移除"}


@router.post("/{room_id}/members/{member_user_id}/mute")
async def mute_member(
    room_id: int,
    member_user_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """禁言成员（管理员以上）。minutes=0 解除。"""
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    m = await S.is_member(db, room_id=room_id, user_id=member_user_id)
    if not m:
        raise NotFoundError("该用户不在群里")
    minutes = int(body.get("minutes") or 0)
    m.muted_until = None if minutes <= 0 else _now_ms() + minutes * 60_000
    await db.flush()
    return {"message": "已解除禁言" if minutes <= 0 else f"已禁言 {minutes} 分钟"}


@router.post("/{room_id}/announcement")
async def set_announcement(
    room_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """设置群公告（管理员以上）。"""
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    room.announcement = (body.get("announcement") or "").strip()[:1000] or None
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "announcement", "room_id": room.id, "announcement": room.announcement})
    return {"message": "已更新公告"}


# ==================== 群资料 / 群主 / 退群 / 清空（QQ 式）====================
@router.patch("/{room_id}")
async def update_room(
    room_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """修改群资料（名称/头像/公告）。管理员以上。"""
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise ValidationError("群名称不能为空")
        room.name = name[:128]
    if "avatar" in body:
        settings_ = dict(room.settings or {})
        settings_["avatar"] = (body.get("avatar") or None)
        room.settings = settings_
    if "announcement" in body:
        room.announcement = (body.get("announcement") or "").strip()[:1000] or None
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id, payload={
        "type": "room_updated", "room_id": room.id, "name": room.name, "announcement": room.announcement,
    })
    return {"message": "已保存", "name": room.name}


@router.post("/{room_id}/transfer")
async def transfer_owner(
    room_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """转让群主（仅现任群主或租户管理员）。默认大群不可转让。"""
    room = await _guard_room(db, user, room_id)
    if room.is_default:
        raise PermissionDeniedError("全员大群不支持转让群主")
    if room.owner_id != user.id and not user.is_admin:
        raise PermissionDeniedError("仅群主可转让群主")
    new_uid = int(body.get("user_id") or 0)
    if not await S.is_member(db, room_id=room_id, user_id=new_uid):
        raise ConflictError("对方不是群成员")
    # 原群主降为普通成员，新群主升为 owner
    old = await db.execute(select(ChatRoomMember).where(
        ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == room.owner_id))
    old_m = old.scalar_one_or_none()
    if old_m:
        old_m.role = "member"
    new_m = (await db.execute(select(ChatRoomMember).where(
        ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == new_uid))).scalar_one_or_none()
    if new_m:
        new_m.role = "owner"
    else:
        db.add(ChatRoomMember(tenant_id=room.tenant_id, room_id=room_id, user_id=new_uid, role="owner"))
    room.owner_id = new_uid
    await db.flush()
    return {"message": "已转让群主"}


@router.post("/{room_id}/leave")
async def leave_room(
    room_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """退出群聊（群主需先转让；全员大群不可退）。"""
    room = await _guard_room(db, user, room_id)
    if room.is_default:
        raise PermissionDeniedError("全员大群不可退出")
    if room.owner_id == user.id:
        raise PermissionDeniedError("请先转让群主后再退群")
    m = await db.execute(select(ChatRoomMember).where(
        ChatRoomMember.room_id == room_id, ChatRoomMember.user_id == user.id))
    mm = m.scalar_one_or_none()
    if mm:
        await db.delete(mm)
    await db.flush()
    return {"message": "已退出群聊"}


@router.post("/{room_id}/clear")
async def clear_messages(
    room_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """清空聊天记录（管理员以上；消息软删为占位，保留成员与群结构）。"""
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    from sqlalchemy import update as _upd

    await db.execute(
        _upd(ChatMessage).where(ChatMessage.room_id == room_id, ChatMessage.revoked.is_(False))
        .values(revoked=True, revoked_by=user.id, revoked_at=_now_ms(), content="", attachments=None)
    )
    room.message_count = 0
    room.last_message_at = _now_ms()
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "cleared", "room_id": room.id})
    return {"message": "聊天记录已清空"}


@router.post("/{room_id}/dissolve")
async def dissolve_room(
    room_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解散群（仅群主或租户管理员；全员大群不可解散）。"""
    room = await _guard_room(db, user, room_id)
    if room.is_default:
        raise PermissionDeniedError("全员大群不可解散")
    if room.owner_id != user.id and not user.is_admin:
        raise PermissionDeniedError("仅群主可解散群")
    room.status = "archived"
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "dissolved", "room_id": room.id})
    return {"message": "群已解散"}


# ==================== 机器人 ====================
@router.post("/{room_id}/bots")
async def add_bot(
    room_id: int,
    body: dict,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """把智能体作为机器人拉进群（@ 才响应）。管理员以上。"""
    from app.models import Agent

    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    aid = int(body.get("agent_id") or 0)
    ag = await db.get(Agent, aid)
    if not ag or ag.tenant_id != room.tenant_id:
        raise NotFoundError("智能体不存在")
    exists = (
        await db.execute(
            select(ChatRoomMember).where(ChatRoomMember.room_id == room_id, ChatRoomMember.agent_id == aid)
        )
    ).scalar_one_or_none()
    if exists:
        return {"message": "该机器人已在群里"}
    db.add(ChatRoomMember(tenant_id=room.tenant_id, room_id=room_id, agent_id=aid, role="member", added_by=user.id))
    await db.flush()
    await broadcaster.broadcast_room(tenant_id=room.tenant_id, room_id=room.id,
                                     payload={"type": "bot_added", "room_id": room.id, "agent_id": aid, "name": ag.name})
    return {"message": f"已添加机器人「{ag.name}」"}


@router.delete("/{room_id}/bots/{agent_id}")
async def remove_bot(
    room_id: int,
    agent_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    room = await _guard_room(db, user, room_id)
    role = await S.member_role(db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
    _require_admin_role(role)
    m = (
        await db.execute(
            select(ChatRoomMember).where(ChatRoomMember.room_id == room_id, ChatRoomMember.agent_id == agent_id)
        )
    ).scalar_one_or_none()
    if m:
        await db.delete(m)
        await db.flush()
    return {"message": "已移除机器人"}


async def _guard_room(db: AsyncSession, user: User, room_id: int) -> ChatRoom:
    room = await db.get(ChatRoom, room_id)
    if not room or room.tenant_id != user.tenant_id:
        raise NotFoundError("房间不存在")
    if not await S.can_access(db, room=room, user_id=user.id, is_admin=bool(user.is_admin)):
        raise PermissionDeniedError("你不是该聊天成员")
    return room


# ==================== WebSocket ====================
async def _ws_authenticate(token: str) -> User | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    async with AsyncSessionLocal() as db:
        u = await db.get(User, int(payload.get("sub", 0)))
        if not u or u.status != "active":
            return None
        if int(payload.get("tv", 0)) != int(getattr(u, "token_version", 0) or 0):
            return None
        if getattr(u, "approval_status", "approved") != "approved":
            return None
        return u


@router.websocket("/ws")
async def chat_ws(ws: WebSocket, token: str = Query("")):
    """实时推送：客户端连上后会自动加入「我可见的全部房间」，收到新消息/撤回/置顶等事件。

    协议：服务端→客户端 {"type":"message"|"revoke"|"pin"|"announcement"|"bot_added", ...}
    客户端→服务端 仅心跳 {"type":"ping"}。
    """
    user = await _ws_authenticate(token)
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    joined: set[int] = set()
    try:
        # 连上时把该用户可见的房间全部订阅（含后续新建的通过 refresh 消息加入）
        async with AsyncSessionLocal() as db:
            rooms = await S.list_rooms(db, tenant_id=user.tenant_id, user_id=user.id, is_admin=bool(user.is_admin))
        for r in rooms:
            await broadcaster.join(tenant_id=user.tenant_id, room_id=r["id"], user_id=user.id, ws=ws)
            joined.add(r["id"])
        await ws.send_json({"type": "ready", "room_ids": list(joined)})
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif isinstance(data, dict) and data.get("type") == "subscribe":
                # 前端新建群/私聊后可让 WS 补订阅
                rid = int(data.get("room_id") or 0)
                if rid and rid not in joined:
                    async with AsyncSessionLocal() as db:
                        room = await db.get(ChatRoom, rid)
                        ok = room and room.tenant_id == user.tenant_id and await S.can_access(
                            db, room=room, user_id=user.id, is_admin=bool(user.is_admin))
                    if ok:
                        await broadcaster.join(tenant_id=user.tenant_id, room_id=rid, user_id=user.id, ws=ws)
                        joined.add(rid)
                        await ws.send_json({"type": "subscribed", "room_id": rid})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger

        get_logger("chat_ws").exception("ws_error", user_id=user.id)
    finally:
        for rid in joined:
            await broadcaster.leave(tenant_id=user.tenant_id, room_id=rid, user_id=user.id, ws=ws)
