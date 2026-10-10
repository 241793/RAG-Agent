"""群聊作用域工具：让「群管机器人」替管理员管理群。

设计要点
- 仅当机器人在某群被 @ 时随本次运行装配（ToolContext.room_id 非空），不进入全局工具池。
- 权限：以机器人在**该群的角色**放行。owner/admin 才可执行管理类写操作；
  普通成员机器人只能只读（列成员/搜索/统计/发消息）。
- 所有写操作直接生效并广播到群（机器人无人值守语义），返回文本回灌 LLM。
- 复用 chat_room_service（S）与 broadcaster，保证与 REST 接口行为一致。
"""
from __future__ import annotations

from app.agents.tools.base import ToolContext, ToolResult
from app.core.errors import AppError

# 允许机器人执行管理操作所需的最小群角色
_ADMIN_ROLES = ("owner", "admin")


async def _room_ctx(ctx: ToolContext):
    """取房间 + 机器人（=ctx.agent_id）在群内角色。返回 (room, role) 或抛错。"""
    from app.models import ChatRoom
    from app.services import chat_room_service as S

    if not ctx.room_id:
        raise AppError("该工具仅能在群聊中被机器人使用")
    room = await ctx.db.get(ChatRoom, ctx.room_id)
    if not room or room.tenant_id != ctx.tenant_id:
        raise AppError("群聊不存在")
    role = await _bot_role(ctx, room)
    return room, role


async def _bot_role(ctx: ToolContext, room) -> str:
    """机器人在该群的角色：owner/admin/member。租户管理员等同 owner。"""
    from sqlalchemy import select

    from app.models import ChatRoomMember

    if room.owner_id == ctx.agent_id:
        return "owner"
    if ctx.agent_id:
        m = (
            await ctx.db.execute(
                select(ChatRoomMember).where(
                    ChatRoomMember.room_id == room.id, ChatRoomMember.agent_id == ctx.agent_id
                )
            )
        ).scalar_one_or_none()
        if m and m.role:
            return m.role
    return "member"


async def _require_admin(ctx: ToolContext, room) -> None:
    role = await _bot_role(ctx, room)
    if role not in _ADMIN_ROLES:
        raise AppError(f"机器人当前在群内角色为「{role}」，需管理员/群主才能执行该操作")


class _RoomTool:
    """群聊工具基类：read 子类直接执行；write 子类需管理员角色。"""

    kind = "read"
    required_permission = "chat:use"
    require_room = True
    admin_only = False

    def __init__(self, *, room_id: int | None = None) -> None:
        self._bound_room_id = room_id

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        # 运行时把房间 id 绑定进 ctx（react 循环已注入，双保险）
        if self._bound_room_id and not ctx.room_id:
            ctx.room_id = self._bound_room_id
        try:
            room, role = await _room_ctx(ctx)
            if self.admin_only and role not in _ADMIN_ROLES:
                return ToolResult(
                    content=f"无权限：机器人需为群管理员/群主才能执行（当前：{role}）", is_error=True
                )
            return await self.execute(args, ctx, room)
        except AppError as e:
            return ToolResult(content=str(e), is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"执行失败：{str(e)[:200]}", is_error=True)

    async def execute(self, args: dict, ctx: ToolContext, room) -> ToolResult:
        raise NotImplementedError


# ==================== 只读类 ====================
class ListRoomMembersTool(_RoomTool):
    name = "room_list_members"
    description = "列出当前群的全部成员（含角色：群主/管理员/成员，及是否机器人）。"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args, ctx, room) -> ToolResult:
        from sqlalchemy import select

        from app.models import ChatRoomMember, User

        rows = (
            await ctx.db.execute(select(ChatRoomMember).where(ChatRoomMember.room_id == room.id))
        ).scalars().all()
        lines = [f"群「{room.name}」共 {len(rows)} 名成员："]
        for m in rows:
            if m.agent_id:
                who = f"机器人#{m.agent_id}"
                nm = await _agent_name(ctx, m.agent_id)
                if nm:
                    who = f"{nm}（机器人）"
            else:
                u = await ctx.db.get(User, m.user_id)
                who = (u.display_name or u.username) if u else f"用户#{m.user_id}"
            role = {"owner": "群主", "admin": "管理员", "member": "成员"}.get(m.role, m.role)
            lines.append(f"- {who}：{role}")
        return ToolResult(content="\n".join(lines), data={"count": len(rows)})


async def _agent_name(ctx: ToolContext, agent_id: int) -> str | None:
    from app.models import Agent

    ag = await ctx.db.get(Agent, agent_id)
    return ag.name if ag else None


class SearchRoomMessagesTool(_RoomTool):
    name = "room_search_messages"
    description = "在当前群的历史消息中按关键词搜索，返回命中的消息（发送者/时间/内容）。"
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "最多返回条数，默认 20"},
        },
        "required": ["keyword"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services import chat_room_service as S

        kw = str(args.get("keyword") or "").strip()
        if not kw:
            return ToolResult(content="请提供搜索关键词", is_error=True)
        limit = max(1, min(int(args.get("limit") or 20), 50))
        rows = await S.search_messages(ctx.db, room_id=room.id, keyword=kw, limit=limit)
        nm = await S.name_map_for(ctx.db, rows)
        lines = [f"群「{room.name}」中匹配「{kw}」的 {len(rows)} 条消息："]
        for m in rows:
            sender = nm.get(m.sender_id or 0, {}).get("name") or "未知"
            lines.append(f"- [{sender}] {m.content[:200]}")
        return ToolResult(content="\n".join(lines) or "（无匹配）", data={"count": len(rows)})


class RoomStatsTool(_RoomTool):
    name = "room_stats"
    description = "统计当前群：成员数、消息总数、近 7 天消息活跃度、发言 Top 成员。用于生成日报/周报/月报。"
    parameters = {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "统计最近多少天，默认 7"},
        },
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services import chat_room_service as S

        days = max(1, min(int(args.get("days") or 7), 90))
        stats = await S.room_stats(ctx.db, room=room, days=days)
        lines = [
            f"群「{room.name}」统计（最近 {days} 天）：",
            f"- 成员数：{stats['member_count']}",
            f"- 消息总数：{stats['message_count']}",
            f"- 近 {days} 天消息数：{stats['recent_count']}",
            f"- 活跃成员数：{stats['active_users']}",
        ]
        if stats.get("top_speakers"):
            top = "、".join(f"{n}({c})" for n, c in stats["top_speakers"])
            lines.append(f"- 发言最多：{top}")
        if stats.get("recent_snippets"):
            lines.append("- 近期讨论要点：")
            for s in stats["recent_snippets"]:
                lines.append(f"  · {s}")
        return ToolResult(content="\n".join(lines), data=stats)


# ==================== 写操作类（需管理员角色）====================
async def _send_room_message(ctx: ToolContext, room, content: str, mentions: list[int] | None = None):
    """以该机器人身份往群里发一条消息并广播，返回落库的消息对象。"""
    from app.services import chat_room_service as S
    from app.services.chat_broadcaster import broadcaster

    msg = await S.post_message(
        ctx.db, room=room, sender_id=ctx.agent_id, sender_type="agent",
        content=content, mentions=mentions or None,
    )
    await ctx.db.flush()
    out = await S.serialize_message(ctx.db, msg)
    await broadcaster.broadcast_room(
        tenant_id=room.tenant_id, room_id=room.id,
        payload={"type": "message", "room_id": room.id, "message": out},
    )
    return msg


class RoomSendMessageTool(_RoomTool):
    name = "room_send_message"
    description = "以机器人身份在当前群发一条消息（可用于发日报/周报/通知）。"
    kind = "read"  # 发消息本身是机器人基本能力，不设管理员门槛
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "消息内容（支持 Markdown）"},
        },
        "required": ["content"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        content = str(args.get("content") or "").strip()
        if not content:
            return ToolResult(content="消息内容不能为空", is_error=True)
        await _send_room_message(ctx, room, content)
        return ToolResult(content="已在群里发送该消息。")


class RoomMuteTool(_RoomTool):
    name = "room_mute_member"
    description = "禁言/解除禁言群内某位成员（按用户名或昵称）。minutes=0 表示解除。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "member": {"type": "string", "description": "成员昵称或用户名"},
            "minutes": {"type": "integer", "description": "禁言分钟数；0=解除禁言"},
        },
        "required": ["member"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from sqlalchemy import select

        from app.models import User
        from app.services import chat_room_service as S

        who = str(args.get("member") or "").strip()
        minutes = int(args.get("minutes") or 0)
        u = await _resolve_user(ctx, room, who)
        if not u:
            return ToolResult(content=f"群里找不到成员「{who}」", is_error=True)
        m = await S.ensure_member_row(ctx.db, tenant_id=room.tenant_id, room_id=room.id, user_id=u.id)
        import time as _t
        m.muted_until = None if minutes <= 0 else int(_t.time() * 1000) + minutes * 60_000
        await ctx.db.flush()
        name = u.display_name or u.username
        return ToolResult(content=f"已{'解除禁言' if minutes <= 0 else f'禁言 {minutes} 分钟'}：{name}")


async def _resolve_user(ctx: ToolContext, room, who: str) -> object | None:
    """按昵称/用户名在群成员里找人（默认大群含全部内部用户）。"""
    from sqlalchemy import select

    from app.models import User

    if not who:
        return None
    rows = (
        await ctx.db.execute(
            select(User).where(User.tenant_id == ctx.tenant_id)
        )
    ).scalars().all()
    for u in rows:
        if (u.username or "") == who or (u.display_name or "") == who:
            return u
    return None


class RoomKickTool(_RoomTool):
    name = "room_remove_member"
    description = "把群内某位成员移出群（按昵称或用户名）。不可移除群主。"
    kind = "write"
    admin_only = True
    dangerous = True
    parameters = {
        "type": "object",
        "properties": {"member": {"type": "string", "description": "成员昵称或用户名"}},
        "required": ["member"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services import chat_room_service as S

        who = str(args.get("member") or "").strip()
        u = await _resolve_user(ctx, room, who)
        if not u:
            return ToolResult(content=f"群里找不到成员「{who}」", is_error=True)
        if u.id == room.owner_id:
            return ToolResult(content="不能移除群主", is_error=True)
        m = await S.get_member_row(ctx.db, room_id=room.id, user_id=u.id)
        if m:
            await ctx.db.delete(m)
            await ctx.db.flush()
        await _send_room_message(ctx, room, f"已将「{u.display_name or u.username}」移出群聊。")
        return ToolResult(content=f"已移除成员：{u.display_name or u.username}")


class RoomSetRoleTool(_RoomTool):
    name = "room_set_role"
    description = "设置/取消某成员的群管理员身份。role=admin 设为管理员；role=member 取消。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "member": {"type": "string", "description": "成员昵称或用户名"},
            "role": {"type": "string", "enum": ["admin", "member"], "description": "目标角色"},
        },
        "required": ["member", "role"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services import chat_room_service as S

        who = str(args.get("member") or "").strip()
        role = str(args.get("role") or "member")
        if role not in ("admin", "member"):
            return ToolResult(content="role 只能为 admin/member", is_error=True)
        u = await _resolve_user(ctx, room, who)
        if not u:
            return ToolResult(content=f"群里找不到成员「{who}」", is_error=True)
        m = await S.ensure_member_row(ctx.db, tenant_id=room.tenant_id, room_id=room.id, user_id=u.id)
        m.role = role
        await ctx.db.flush()
        name = u.display_name or u.username
        return ToolResult(content=f"已将「{name}」设为{'群管理员' if role == 'admin' else '普通成员'}")


class RoomAnnouncementTool(_RoomTool):
    name = "room_post_announcement"
    description = "发布一条群公告（可在群内多条公告中新增）。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {"content": {"type": "string", "description": "公告内容"}},
        "required": ["content"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.models import ChatAnnouncement
        from app.services.chat_broadcaster import broadcaster

        content = str(args.get("content") or "").strip()
        if not content:
            return ToolResult(content="公告内容不能为空", is_error=True)
        ann = ChatAnnouncement(
            tenant_id=room.tenant_id, room_id=room.id, content=content[:2000],
            created_by=ctx.agent_id, pinned=True,
        )
        ctx.db.add(ann)
        room.announcement = content[:2000]
        await ctx.db.flush()
        await broadcaster.broadcast_room(
            tenant_id=room.tenant_id, room_id=room.id,
            payload={"type": "announcement", "room_id": room.id, "announcement": room.announcement},
        )
        return ToolResult(content="已发布群公告。")


class RoomPinTool(_RoomTool):
    name = "room_pin_message"
    description = "置顶或取消置顶某条消息（按消息 id）。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "message_id": {"type": "integer", "description": "消息 id"},
            "pinned": {"type": "boolean", "description": "true=置顶，false=取消", "default": True},
        },
        "required": ["message_id"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.models import ChatMessage
        from app.services.chat_broadcaster import broadcaster

        mid = int(args.get("message_id") or 0)
        pinned = bool(args.get("pinned", True))
        msg = await ctx.db.get(ChatMessage, mid)
        if not msg or msg.room_id != room.id:
            return ToolResult(content="消息不存在", is_error=True)
        msg.pinned = pinned
        await ctx.db.flush()
        await broadcaster.broadcast_room(
            tenant_id=room.tenant_id, room_id=room.id,
            payload={"type": "pin", "room_id": room.id, "message_id": mid, "pinned": pinned},
        )
        return ToolResult(content="已置顶" if pinned else "已取消置顶")


class RoomMuteAllTool(_RoomTool):
    name = "room_mute_all"
    description = (
        "开启/关闭全员禁言（仅群主/管理员机器人可用）。开启后普通成员不能发言，"
        "管理员与机器人不受影响；可传 minutes 设为定时自动解除（0/缺省=手动解除）。"
    )
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "description": "true=开启全员禁言，false=关闭"},
            "minutes": {"type": "integer", "description": "可选：多少分钟后自动解除（仅开启时有效）"},
        },
        "required": ["enabled"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services import chat_room_service as S

        enabled = bool(args.get("enabled"))
        minutes = int(args.get("minutes") or 0)
        await S.set_mute_all(ctx.db, room=room, enabled=enabled, minutes=minutes)
        if enabled:
            tip = f"（{minutes} 分钟后自动解除）" if minutes else ""
            return ToolResult(content=f"已开启全员禁言{tip}。")
        return ToolResult(content="已关闭全员禁言。")


class RoomScheduleTool(_RoomTool):
    name = "room_schedule_task"
    description = (
        "为当前群创建定时任务：到点自动执行一段提示词，并把结果作为机器人消息发到本群。"
        "适合「每天 9 点发日报」「每周一 9 点发周报」「每条 1 号发月报」「每晚 22 点开启全员禁言」等。"
    )
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "任务名称"},
            "prompt": {"type": "string", "description": "到点让机器人执行的提示词，如「生成本群今日聊天日报」"},
            "cron_expr": {"type": "string", "description": "cron 表达式（分 时 日 月 周），如 0 9 * * *"},
            "enabled": {"type": "boolean", "default": True},
        },
        "required": ["name", "prompt", "cron_expr"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services.schedule_service import create_task

        data = {
            "name": str(args.get("name") or "群定时任务"),
            "agent_id": ctx.agent_id,
            "target_type": "prompt",
            "prompt": str(args.get("prompt") or ""),
            "schedule_kind": "cron",
            "cron_expr": str(args.get("cron_expr") or "0 9 * * *"),
            "enabled": bool(args.get("enabled", True)),
            "room_id": room.id,
            "room_bot_agent_id": ctx.agent_id,
            "notify_on": "never",
        }
        t = await create_task(ctx.db, tenant_id=ctx.tenant_id, owner_id=ctx.user_id or 0, data=data)
        return ToolResult(
            content=f"已创建定时任务「{t.name}」（{t.cron_expr}），结果将推送到本群。",
            data={"task_id": t.id},
        )


class RoomRevokeTool(_RoomTool):
    name = "room_revoke_message"
    description = "撤回群内某条消息（按消息 id）。用于处理违规/不当发言。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {"message_id": {"type": "integer", "description": "要撤回的消息 id"}},
        "required": ["message_id"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.models import ChatMessage
        from app.services.chat_broadcaster import broadcaster
        import time as _t

        mid = int(args.get("message_id") or 0)
        msg = await ctx.db.get(ChatMessage, mid)
        if not msg or msg.room_id != room.id:
            return ToolResult(content="消息不存在", is_error=True)
        if msg.revoked:
            return ToolResult(content="该消息已被撤回", is_error=True)
        msg.revoked = True
        msg.revoked_by = ctx.agent_id
        msg.revoked_at = int(_t.time() * 1000)
        msg.content = ""
        msg.attachments = None
        await ctx.db.flush()
        await broadcaster.broadcast_room(
            tenant_id=room.tenant_id, room_id=room.id,
            payload={"type": "revoke", "room_id": room.id, "message_id": mid, "revoked_by": ctx.agent_id},
        )
        return ToolResult(content=f"已撤回消息 #{mid}。")


class RoomWarnTool(_RoomTool):
    name = "room_warn_member"
    description = "在群里 @ 某位成员并发出一条群管理提醒/警告（并可选同时禁言）。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "member": {"type": "string", "description": "成员昵称或用户名"},
            "reason": {"type": "string", "description": "提醒/警告内容"},
            "mute_minutes": {"type": "integer", "description": "可选：同时禁言多少分钟（0=不禁言）"},
        },
        "required": ["member", "reason"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services import chat_room_service as S

        who = str(args.get("member") or "").strip()
        reason = str(args.get("reason") or "").strip()
        mins = int(args.get("mute_minutes") or 0)
        u = await _resolve_user(ctx, room, who)
        if not u:
            return ToolResult(content=f"群里找不到成员「{who}」", is_error=True)
        name = u.display_name or u.username
        if mins > 0:
            m = await S.ensure_member_row(ctx.db, tenant_id=room.tenant_id, room_id=room.id, user_id=u.id)
            import time as _t
            m.muted_until = int(_t.time() * 1000) + mins * 60_000
            await ctx.db.flush()
        tip = f"（并禁言 {mins} 分钟）" if mins > 0 else ""
        await _send_room_message(ctx, room, f"@{name} 请注意：{reason}{tip}", mentions=[u.id])
        return ToolResult(content=f"已提醒成员「{name}」{tip}")


class RoomPinnedTool(_RoomTool):
    name = "room_list_pinned"
    description = "列出本群的置顶消息与最近公告，便于回复群内常见问题。"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args, ctx, room) -> ToolResult:
        from sqlalchemy import select

        from app.models import ChatAnnouncement, ChatMessage
        from app.services import chat_room_service as S

        pinned = (
            await ctx.db.execute(
                select(ChatMessage).where(
                    ChatMessage.room_id == room.id, ChatMessage.pinned.is_(True), ChatMessage.revoked.is_(False)
                ).order_by(ChatMessage.id.desc()).limit(20)
            )
        ).scalars().all()
        anns = (
            await ctx.db.execute(
                select(ChatAnnouncement).where(ChatAnnouncement.room_id == room.id)
                .order_by(ChatAnnouncement.pinned.desc(), ChatAnnouncement.id.desc()).limit(10)
            )
        ).scalars().all()
        lines = []
        if anns:
            lines.append("群公告：")
            for a in anns:
                lines.append(f"- {a.content[:200]}")
        if pinned:
            lines.append("置顶消息：")
            for m in pinned:
                lines.append(f"- [{m.id}] {m.content[:200]}")
        return ToolResult(content="\n".join(lines) or "（暂无置顶消息或公告）")


class RoomQuietModeTool(_RoomTool):
    name = "room_quiet_hours"
    description = "为群设置「静默时段」：到点自动开启全员禁言，次日到点自动解除。适合夜间免打扰。"
    kind = "write"
    admin_only = True
    parameters = {
        "type": "object",
        "properties": {
            "mute_at": {"type": "string", "description": "每天开启禁言的时刻，cron 格式，如 0 22 * * *"},
            "unmute_at": {"type": "string", "description": "每天解除禁言的时刻，如 0 7 * * *"},
        },
        "required": ["mute_at", "unmute_at"],
    }

    async def execute(self, args, ctx, room) -> ToolResult:
        from app.services.schedule_service import create_task

        mute_at = str(args.get("mute_at") or "0 22 * * *")
        unmute_at = str(args.get("unmute_at") or "0 7 * * *")
        base = {"agent_id": ctx.agent_id, "target_type": "prompt", "schedule_kind": "cron",
                "room_id": room.id, "room_bot_agent_id": ctx.agent_id, "notify_on": "never", "enabled": True}
        await create_task(ctx.db, tenant_id=ctx.tenant_id, owner_id=ctx.user_id or 0, data={
            **base, "name": f"静默·开启·{room.name}", "cron_expr": mute_at,
            "prompt": "请开启本群全员禁言（12 小时）。",
        })
        await create_task(ctx.db, tenant_id=ctx.tenant_id, owner_id=ctx.user_id or 0, data={
            **base, "name": f"静默·解除·{room.name}", "cron_expr": unmute_at,
            "prompt": "请关闭本群全员禁言。",
        })
        return ToolResult(content=f"已设置静默时段：{mute_at} 开启禁言，{unmute_at} 解除。")


# 注册给房间作用域使用的工具集合
ROOM_TOOLS = [
    ListRoomMembersTool,
    SearchRoomMessagesTool,
    RoomStatsTool,
    RoomPinnedTool,
    RoomSendMessageTool,
    RoomMuteTool,
    RoomKickTool,
    RoomSetRoleTool,
    RoomAnnouncementTool,
    RoomPinTool,
    RoomMuteAllTool,
    RoomRevokeTool,
    RoomWarnTool,
    RoomQuietModeTool,
    RoomScheduleTool,
]


def build_room_tools(room_id: int) -> list:
    """构造绑定到某群的工具实例列表（供 AgentRunner.extra_tools）。"""
    return [cls(room_id=room_id) for cls in ROOM_TOOLS]
