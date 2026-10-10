"""聊天室机器人：被 @ 时调用 AgentRunner 生成回复并落库/广播。

要点：
- 用独立 session（后台任务，不能依赖请求 session）
- 机器人用自己的「虚拟 PrincipalSet」（能读其绑定 KB），allow_auto_write 避免写工具卡在 HITL
- persist=False，不污染 AI 问答的 Conversation
- 回复消息带 @提问者，并广播到房间
"""
from __future__ import annotations

import time

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import Agent, ChatRoom, User
from app.services import chat_room_service as S
from app.services.chat_broadcaster import broadcaster
from app.services.permission import PrincipalSet

logger = get_logger("chat_bot")

# 同一机器人处理中标记，避免并发重复响应（进程内）
_BUSY: set[tuple[int, int]] = set()


async def maybe_trigger_bots(room_id: int, agent_id: int, content: str, asker_id: int) -> None:
    key = (room_id, agent_id)
    if key in _BUSY:
        return
    _BUSY.add(key)
    try:
        await _run_bot(room_id, agent_id, content, asker_id)
    except Exception:  # noqa: BLE001
        logger.exception("chat_bot_failed", room_id=room_id, agent_id=agent_id)
    finally:
        _BUSY.discard(key)


async def _run_bot(room_id: int, agent_id: int, content: str, asker_id: int) -> None:
    from sqlalchemy import select

    from app.agents.runner import AgentRunner
    from app.middleware.auth_dep import get_user_permission_codes, load_principal_set

    async with AsyncSessionLocal() as db:
        room = await db.get(ChatRoom, room_id)
        agent = await db.get(Agent, agent_id)
        asker = await db.get(User, asker_id)
        if not room or not agent or not asker:
            return
        # 机器人以其绑定的 KB/工具运行，权限用租户管理员（其配置决定实际可用范围）
        admin = (
            await db.execute(
                select(User).where(
                    User.tenant_id == room.tenant_id, User.is_admin.is_(True)
                ).order_by(User.id)
            )
        ).scalars().first()
        principal_user = admin or asker
        ps = await load_principal_set(db, principal_user)
        perms = await get_user_permission_codes(db, principal_user)

        # 房间作用域群管工具：机器人在本群的角色决定可用写操作（owner/admin 才放行）
        from app.agents.tools.chat_room_tools import build_room_tools

        room_tools = build_room_tools(room_id)

        runner = AgentRunner(
            db, agent=agent, ps=ps, conversation=None, history=[], perms=perms,
            summary=None, persist=False, allow_auto_write=True,
            room_id=room_id, extra_tools=room_tools,
        )
        # 去掉开头的 @机器人名，作为真正的问题
        query = content
        for pref in (f"@{agent.name}", "@"):
            if query.strip().startswith(pref):
                query = query.strip()[len(pref):].strip()
                break
        if not query:
            query = "你好"

        text = ""
        try:
            async for evt in runner.run(query):
                if evt.get("type") == "delta":
                    text += evt.get("text", "")
                elif evt.get("type") == "error":
                    text = text or "（机器人处理出错）"
        except Exception as e:  # noqa: BLE001
            logger.warning("chat_bot_run_error", err=str(e)[:200])
            text = text or "（机器人暂时无法回答）"

        if not text.strip():
            text = "（我没有得到有效回答）"

        # 落库 + 广播，回复 @ 提问者
        asker_name = asker.display_name or asker.username
        msg = await S.post_message(
            db, room=room, sender_id=agent_id, sender_type="agent",
            content=f"@{asker_name} {text}", mentions=[asker_id],
        )
        await db.flush()
        out = await S.serialize_message(db, msg)
        await db.commit()

    await broadcaster.broadcast_room(
        tenant_id=room.tenant_id, room_id=room_id,
        payload={"type": "message", "room_id": room_id, "message": out},
    )
