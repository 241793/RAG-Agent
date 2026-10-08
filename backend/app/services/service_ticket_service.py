"""客服工单服务：建单、指派、通知客服、回复回发渠道、关闭。

供渠道 dispatcher（用户请求转人工）、客服后台 API、AI 工具共用，保证行为一致。
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("service_ticket")

# SLA 首响时限（分钟），按优先级
_SLA_MINUTES = {"urgent": 60, "high": 4 * 60, "normal": 24 * 60, "low": 72 * 60}


def _sla_due(priority: str, now_ms: int) -> int:
    return now_ms + _SLA_MINUTES.get(priority, 24 * 60) * 60 * 1000


async def create_ticket(
    db: AsyncSession, *, tenant_id: int, subject: str, content: str,
    channel_id: int | None = None, channel_kind: str | None = None,
    external_user: str | None = None, external_group: str | None = None,
    channel_user_id: int | None = None, conversation_id: int | None = None,
    created_by: int | None = None, priority: str = "normal",
    category: str | None = None, tags: list | None = None,
    customer_lang: str | None = None, source: str = "channel",
    notify: bool = True,
):
    """建工单。notify=True 时通知客服（站内+已配置外渠）。

    自动计算 SLA 首响截止时间；建单后发 ticket.created 事件。
    """
    from app.models import ServiceTicket

    now = int(time.time() * 1000)
    t = ServiceTicket(
        tenant_id=tenant_id, subject=(subject or "")[:512], status="open", priority=priority,
        channel_id=channel_id, channel_kind=channel_kind, source=source,
        external_user=external_user, external_group=external_group,
        channel_user_id=channel_user_id, conversation_id=conversation_id,
        created_by=created_by, category=category, tags=tags or None,
        customer_lang=customer_lang,
        messages=[{"role": "user", "content": content, "ts": now}],
        last_message_at=now, sla_due_at=_sla_due(priority, now),
    )
    db.add(t)
    await db.flush()

    if notify:
        await _notify_staff(db, t, content)
    await _publish("ticket.created", t)
    return t


async def _publish(event: str, ticket) -> None:
    """发工单事件（供自动化：定时任务/工作流消费）。失败不阻断。"""
    try:
        from app.tasks.event_bus import publish

        await publish(event, tenant_id=ticket.tenant_id, payload={
            "ticket_id": ticket.id, "status": ticket.status, "priority": ticket.priority,
            "category": ticket.category, "external_user": ticket.external_user,
        })
    except Exception:  # noqa: BLE001
        logger.exception("ticket_event_failed", event=event, ticket_id=getattr(ticket, "id", 0))


async def _notify_staff(db: AsyncSession, ticket, content: str) -> None:
    """通知客服有新工单（站内 + 外渠）。失败不影响建单。"""
    try:
        from app.notifiers.base import NotificationMessage
        from app.notifiers.registry import dispatch

        # 有指派人发给指派人；否则发给租户管理员（user_id=None → 仅外渠/兜底站内）
        body = f"来源：{ticket.channel_kind or '问答页'}\n{content[:300]}"
        msg = NotificationMessage(
            title=f"新客服工单 #{ticket.id}：{ticket.subject or '待处理'}",
            body=body, level="warning", kind="service",
            link="/service-tickets", ref_type="service_ticket", ref_id=ticket.id,
            user_id=ticket.assignee_id,
        )
        await dispatch(db, tenant_id=ticket.tenant_id, msg=msg, user_id=ticket.assignee_id)
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("ticket_notify_failed", ticket_id=ticket.id)


async def add_agent_reply(db: AsyncSession, ticket, content: str, *, agent_id: int) -> dict:
    """客服回复：追加到消息流，记录首次响应时间，并尝试回发到原渠道。"""
    now = int(time.time() * 1000)
    msgs = list(ticket.messages or [])
    msgs.append({"role": "agent", "content": content, "ts": now, "agent_id": agent_id})
    ticket.messages = msgs
    ticket.last_message_at = now
    if ticket.first_response_at is None:
        ticket.first_response_at = now  # SLA 首响
    if ticket.status == "open":
        ticket.status = "pending"
    if ticket.assignee_id is None:
        ticket.assignee_id = agent_id
    await db.flush()

    sent = await _send_to_channel(ticket, content)
    await _publish("ticket.replied", ticket)
    return {"ok": True, "sent_to_channel": sent}


async def _send_to_channel(ticket, content: str) -> bool:
    """把客服回复发回来源渠道。"""
    if not ticket.channel_id:
        return False
    try:
        from app.channels.base import OutboundMessage
        from app.channels.manager import channel_manager

        kwargs = {}
        if ticket.external_group:
            kwargs["group_id"] = ticket.external_group
        elif ticket.external_user:
            kwargs["user_id"] = ticket.external_user
        else:
            return False
        out = OutboundMessage(content=content, **kwargs)
        return await channel_manager.send_with_fallback(ticket.channel_id, ticket.channel_kind, out)
    except Exception:  # noqa: BLE001
        logger.exception("ticket_reply_send_failed", ticket_id=ticket.id)
        return False


async def close_ticket(db: AsyncSession, ticket, *, resolution: str | None = None) -> None:
    now = int(time.time() * 1000)
    ticket.status = "closed"
    ticket.closed_at = now
    if resolution:
        ticket.resolution = resolution[:2000]
    await db.flush()
    await _publish("ticket.closed", ticket)


async def add_note(db: AsyncSession, ticket, content: str, *, agent_id: int) -> None:
    """追加内部备注（仅客服可见，不发给客户）。"""
    now = int(time.time() * 1000)
    notes = list(ticket.internal_notes or [])
    notes.append({"content": content, "ts": now, "agent_id": agent_id})
    ticket.internal_notes = notes
    await db.flush()


async def rate_ticket(db: AsyncSession, ticket, score: int, comment: str | None = None) -> None:
    """客户满意度评价（1-5）。"""
    if not (1 <= int(score) <= 5):
        raise ValueError("满意度需 1-5")
    ticket.satisfaction = int(score)
    if comment:
        ticket.satisfaction_comment = comment[:1000]
    await db.flush()
    await _publish("ticket.rated", ticket)


async def scan_sla_breaches(db: AsyncSession, tenant_id: int | None = None) -> int:
    """扫描超时未首响的工单，标 sla_breached 并发 ticket.timeout 事件。返回命中数。"""
    from app.models import ServiceTicket

    now = int(time.time() * 1000)
    cond = [
        ServiceTicket.status.in_(("open", "pending")),
        ServiceTicket.sla_due_at.is_not(None),
        ServiceTicket.sla_due_at < now,
        ServiceTicket.first_response_at.is_(None),
        ServiceTicket.sla_breached.is_(False),
    ]
    if tenant_id is not None:
        cond.append(ServiceTicket.tenant_id == tenant_id)
    rows = (await db.execute(select(ServiceTicket).where(*cond))).scalars().all()
    for t in rows:
        t.sla_breached = True
        await db.flush()
        await _publish("ticket.timeout", t)
        try:
            from app.notifiers.base import NotificationMessage
            from app.notifiers.registry import dispatch

            await dispatch(db, tenant_id=t.tenant_id, user_id=t.assignee_id, msg=NotificationMessage(
                title=f"工单 #{t.id} 已超时未响应", body=f"{t.subject}", level="error",
                kind="service", link="/service-tickets", ref_type="service_ticket", ref_id=t.id,
                user_id=t.assignee_id,
            ))
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("sla_notify_failed", ticket_id=t.id)
    return len(rows)


async def list_tickets(
    db: AsyncSession, *, tenant_id: int, status: str | None = None,
    assignee_id: int | None = None, priority: str | None = None,
    source: str | None = None, limit: int = 50,
) -> list:
    from app.models import ServiceTicket

    q = select(ServiceTicket).where(ServiceTicket.tenant_id == tenant_id)
    if status:
        q = q.where(ServiceTicket.status == status)
    if assignee_id:
        q = q.where(ServiceTicket.assignee_id == assignee_id)
    if priority:
        q = q.where(ServiceTicket.priority == priority)
    if source:
        q = q.where(ServiceTicket.source == source)
    q = q.order_by(ServiceTicket.id.desc()).limit(min(limit, 200))
    return list((await db.execute(q)).scalars().all())


async def resolve_ticket(db: AsyncSession, ticket, *, resolution: str | None = None) -> None:
    """标记工单为「已解决」（客户问题已处理，等待关闭/评价）。"""
    if resolution:
        ticket.resolution = resolution[:2000]
    ticket.status = "resolved"
    await db.flush()
    await _publish("ticket.resolved", ticket)


# 批量操作允许的动作
BULK_ACTIONS = ("close", "resolve", "assign", "priority", "tag", "reopen")


async def bulk_update(
    db: AsyncSession, *, tenant_id: int, ids: list[int], action: str, value=None,
) -> dict:
    """批量工单操作。返回 {updated, skipped}。逐条落审计由调用方负责汇总。"""
    from app.models import ServiceTicket

    if action not in BULK_ACTIONS:
        raise ValueError(f"不支持的批量动作：{action}")
    rows = (await db.execute(
        select(ServiceTicket).where(
            ServiceTicket.tenant_id == tenant_id, ServiceTicket.id.in_(ids)
        )
    )).scalars().all()
    found = {t.id for t in rows}
    updated = 0
    now = int(time.time() * 1000)
    for t in rows:
        if action == "close":
            t.status = "closed"; t.closed_at = now
            await _publish("ticket.closed", t)
        elif action == "resolve":
            t.status = "resolved"
            await _publish("ticket.resolved", t)
        elif action == "reopen":
            t.status = "open"; t.closed_at = None
        elif action == "assign":
            t.assignee_id = int(value) if value is not None else None
        elif action == "priority":
            t.priority = str(value or "normal")
        elif action == "tag":
            tags = list(t.tags or [])
            v = str(value or "").strip()
            if v and v not in tags:
                tags.append(v)
            t.tags = tags
        updated += 1
    await db.flush()
    return {"updated": updated, "skipped": len(set(ids) - found)}



async def find_open_ticket(
    db: AsyncSession, *, tenant_id: int, channel_id: int, external_user: str,
    external_group: str | None = None,
) -> object | None:
    """查该渠道用户是否有进行中（未关闭）的工单。用于「已有工单则续聊而非重复建单」。"""
    from app.models import ServiceTicket

    cond = [
        ServiceTicket.tenant_id == tenant_id,
        ServiceTicket.channel_id == channel_id,
        ServiceTicket.external_user == external_user,
        ServiceTicket.status.in_(("open", "pending")),
    ]
    if external_group:
        cond.append(ServiceTicket.external_group == external_group)
    return (await db.execute(
        select(ServiceTicket).where(*cond).order_by(ServiceTicket.id.desc()).limit(1)
    )).scalars().first()


async def add_user_message(db: AsyncSession, ticket, content: str) -> None:
    """把用户的后续消息追加到工单消息流（工单进行中时，用户消息应进入工单而非 AI）。

    若该工单开启了提醒（watch）且全局开关为真，则通知客服「有新回复」。
    """
    now = int(time.time() * 1000)
    msgs = list(ticket.messages or [])
    msgs.append({"role": "user", "content": content, "ts": now})
    ticket.messages = msgs
    ticket.last_message_at = now
    if ticket.status == "open":
        ticket.status = "pending"  # 用户已补充信息 → 待客服处理
    await db.flush()

    if not _reply_notify_enabled(ticket):
        return
    try:
        from app.notifiers.base import NotificationMessage
        from app.notifiers.registry import dispatch

        msg = NotificationMessage(
            title=f"工单 #{ticket.id} 有新的客户回复",
            body=(content or "")[:300], level="info", kind="service",
            link="/service-tickets", ref_type="service_ticket", ref_id=ticket.id,
            user_id=ticket.assignee_id,
        )
        await dispatch(db, tenant_id=ticket.tenant_id, msg=msg, user_id=ticket.assignee_id)
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("ticket_reply_notify_failed", ticket_id=ticket.id)


def _reply_notify_enabled(ticket) -> bool:
    """是否通知：工单 watch 且全局 service_notify_on_reply。"""
    from app.core.config import settings

    if getattr(ticket, "watch", True) is False:
        return False
    return bool(getattr(settings, "service_notify_on_reply", True))


async def customer_context(db: AsyncSession, ticket) -> dict:
    """客服工作台：该外部客户的历史上下文（工单数、渠道、最近对话）。"""
    from sqlalchemy import func as _func

    from app.models import Message, ServiceTicket

    base = [
        ServiceTicket.tenant_id == ticket.tenant_id,
        ServiceTicket.external_user == ticket.external_user,
    ]
    total = (await db.execute(select(_func.count()).select_from(ServiceTicket).where(*base))).scalar_one()
    open_cnt = (await db.execute(
        select(_func.count()).select_from(ServiceTicket).where(*base, ServiceTicket.status.in_(("open", "pending")))
    )).scalar_one()
    history = (await db.execute(
        select(ServiceTicket).where(*base).order_by(ServiceTicket.id.desc()).limit(10)
    )).scalars().all()
    recent_msgs: list[dict] = []
    if ticket.conversation_id:
        rows = (await db.execute(
            select(Message).where(Message.conversation_id == ticket.conversation_id)
            .order_by(Message.id.desc()).limit(10)
        )).scalars().all()
        recent_msgs = [{"role": m.role, "content": (m.content or "")[:300], "ts": m.created_at}
                       for m in reversed(rows)]
    return {
        "external_user": ticket.external_user,
        "channel_kind": ticket.channel_kind,
        "ticket_total": total,
        "ticket_open": open_cnt,
        "history": [{"id": t.id, "subject": t.subject, "status": t.status, "created_at": t.created_at}
                    for t in history],
        "recent_messages": recent_msgs,
    }


async def list_channel_conversations(db: AsyncSession, *, tenant_id: int, limit: int = 50) -> list:
    """列出渠道来源的会话（供客服主管抽查/质检）。附最后一条消息摘要 + 客户备注。"""
    from app.models import ChannelUser, Conversation, Message

    rows = (await db.execute(
        select(Conversation).where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.id.desc()).limit(min(limit, 200))
    )).scalars().all()
    out = []
    for c in rows:
        st = c.settings or {}
        if not st.get("channel"):
            continue
        last = (await db.execute(
            select(Message).where(Message.conversation_id == c.id)
            .order_by(Message.id.desc()).limit(1)
        )).scalars().first()
        # 客户备注（存在 ChannelUser 上，按 channel + external_id 找）
        cu = (await db.execute(
            select(ChannelUser).where(
                ChannelUser.tenant_id == tenant_id,
                ChannelUser.channel == st.get("channel"),
                ChannelUser.external_id == st.get("external_id"),
            )
        )).scalars().first()
        out.append({
            "id": c.id, "title": c.title, "channel": st.get("channel"),
            "external_id": st.get("external_id"), "message_count": c.message_count,
            "owner_id": c.user_id, "channel_user_id": cu.id if cu else None,
            "note": (cu.note if cu else None),
            "last_message": (last.content or "")[:80] if last else "",
            "last_at": last.created_at if last else None,
        })
    return out


async def set_customer_note(db: AsyncSession, *, tenant_id: int, channel_user_id: int, note: str) -> dict:
    """保存某个渠道客户（ChannelUser）的备注（仅内部可见）。"""
    from app.models import ChannelUser

    cu = await db.get(ChannelUser, channel_user_id)
    if not cu or cu.tenant_id != tenant_id:
        raise ValueError("客户不存在")
    cu.note = (note or "")[:2000] or None
    await db.flush()
    return {"ok": True, "note": cu.note}


async def conversation_messages(
    db: AsyncSession, *, conversation_id: int, tenant_id: int, limit: int = 200,
) -> list[dict]:
    """读取渠道会话的完整消息（含附件/产物），供客服查看往来记录。跨租户拒绝。"""
    from app.models import Conversation, Message

    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.tenant_id != tenant_id:
        raise ValueError("会话不存在")
    rows = (await db.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc()).limit(min(limit, 500))
    )).scalars().all()
    return [{
        "id": m.id, "role": m.role, "content": m.content,
        "attachments": m.attachments or [], "artifacts": m.artifacts or [],
        "created_at": m.created_at, "model": m.model,
    } for m in rows]


async def add_conversation_note(db, conversation, content: str, *, agent_id: int) -> dict:
    """在渠道会话上添加内部备注（存 conversation.settings._notes，仅客服可见）。"""
    now = int(time.time() * 1000)
    st = dict(conversation.settings or {})
    notes = list(st.get("_notes") or [])
    notes.append({"content": content, "ts": now, "agent_id": agent_id})
    st["_notes"] = notes
    conversation.settings = st
    await db.flush()
    return {"ok": True, "notes": notes}


def set_conversation_watch(conversation, watch: bool) -> None:
    """设置渠道会话的「有新回复通知我」开关。"""
    st = dict(conversation.settings or {})
    st["_watch"] = bool(watch)
    conversation.settings = st


async def notify_conversation_reply(db, conversation, content: str) -> None:
    """渠道会话收到客户新消息时通知客服（受会话 watch + 全局开关约束）。"""
    from app.core.config import settings

    st = conversation.settings or {}
    if st.get("_watch", True) is False:
        return
    if not bool(getattr(settings, "service_notify_on_reply", True)):
        return
    try:
        from app.notifiers.base import NotificationMessage
        from app.notifiers.registry import dispatch

        ch = st.get("channel") or ""
        msg = NotificationMessage(
            title=f"渠道会话 #{conversation.id} 有新消息",
            body=(content or "")[:300], level="info", kind="service",
            link="/service-tickets", ref_type="conversation", ref_id=conversation.id,
        )
        await dispatch(db, tenant_id=conversation.tenant_id, msg=msg)
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("conversation_reply_notify_failed", conversation_id=conversation.id)


async def reply_in_conversation(
    db: AsyncSession, *, conversation, content: str, agent_id: int,
) -> dict:
    """客服在渠道会话内回复：落库为 agent 消息 + 回发客户渠道。

    若该客户有进行中的工单，同步进工单消息流，保持两处一致。
    """
    from app.models import Message

    now = int(time.time() * 1000)
    db.add(Message(
        tenant_id=conversation.tenant_id, conversation_id=conversation.id,
        role="agent", content=content, created_at=now,
    ))
    await db.flush()

    # 回发到原渠道
    sent = False
    st = conversation.settings or {}
    channel_id = st.get("channel_id")
    if channel_id:
        try:
            from app.channels.base import OutboundMessage
            from app.channels.manager import channel_manager

            ext_user = st.get("external_id")
            ext_group = st.get("external_group")
            kwargs = {}
            if ext_group:
                kwargs["group_id"] = ext_group
            elif ext_user:
                kwargs["user_id"] = ext_user
            if kwargs:
                sent = await channel_manager.send_with_fallback(
                    channel_id, st.get("channel"), OutboundMessage(content=content, **kwargs))
        except Exception:  # noqa: BLE001
            logger.exception("conversation_reply_send_failed", conversation_id=conversation.id)

    # 同步进进行中的工单（若有）
    existing = await find_open_ticket(
        db, tenant_id=conversation.tenant_id, channel_id=channel_id or 0,
        external_user=st.get("external_id") or "", external_group=st.get("external_group"),
    )
    if existing is not None:
        await add_agent_reply(db, existing, content, agent_id=agent_id)

    return {"ok": True, "sent_to_channel": sent}


async def send_attachment_in_conversation(
    db: AsyncSession, *, conversation, agent_id: int, file_key: str, name: str,
    mime: str, size: int, kind: str = "document",
) -> dict:
    """客服在渠道会话内发送附件：先落库展示，再尽力回发渠道。

    kind：image / video / document。渠道不支持媒体时客户至少收到文字提示。
    """
    from app.core.security import create_file_token
    from app.models import Message

    now = int(time.time() * 1000)
    signed = create_file_token(scope="attachment", tenant_id=conversation.tenant_id, file_key=file_key)
    att = {
        "type": kind, "file_key": file_key, "name": name, "mime": mime, "size": size,
        "url": f"/api/v1/chat/attachments/{file_key}?t={signed}",
    }
    db.add(Message(
        tenant_id=conversation.tenant_id, conversation_id=conversation.id,
        role="agent", content="", created_at=now, attachments=[att],
    ))
    await db.flush()

    sent = False
    st = conversation.settings or {}
    channel_id = st.get("channel_id")
    if channel_id:
        try:
            from app.channels.base import OutboundMessage
            from app.channels.manager import channel_manager
            from app.ingest.storage import get_storage

            kwargs = {}
            if st.get("external_group"):
                kwargs["group_id"] = st["external_group"]
            elif st.get("external_id"):
                kwargs["user_id"] = st["external_id"]
            if kwargs:
                try:
                    data = get_storage().read(file_key)
                except Exception:  # noqa: BLE001
                    data = None
                media = [{"type": kind if kind in ("image", "video") else "file",
                          "name": name, "mime": mime, "data": data}] if data else []
                # 文本兜底：渠道发不了媒体时客户仍能看到文件名
                fallback = f"[客服发送了附件：{name}]"
                sent = await channel_manager.send_with_fallback(
                    channel_id, st.get("channel"), OutboundMessage(content=fallback, media=media, **kwargs)
                )
        except Exception:  # noqa: BLE001
            logger.exception("conversation_attachment_send_failed", conversation_id=conversation.id)

    # 同步进进行中的工单（若该客户有工单）
    existing = await find_open_ticket(
        db, tenant_id=conversation.tenant_id, channel_id=channel_id or 0,
        external_user=st.get("external_id") or "", external_group=st.get("external_group"),
    )
    if existing is not None:
        msgs = list(existing.messages or [])
        msgs.append({"role": "agent", "content": f"[附件] {name}", "ts": now,
                     "agent_id": agent_id, "attachments": [att]})
        existing.messages = msgs
        existing.last_message_at = now
        if existing.status == "open":
            existing.status = "pending"
        await db.flush()

    return {"ok": True, "sent_to_channel": sent, "attachment": att}
