"""客服工单接口：列表/详情/建单/回复/指派/改状态/关闭。

渠道用户请求「转人工」时由 dispatcher 自动建单；客服在此回复，回复会回发到原渠道。
权限：新权限码 service:read / service:manage。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import require_permission
from app.models import User
from app.schemas.service_ticket import (
    QuickReplyCreate,
    QuickReplyOut,
    QuickReplyUpdate,
    TicketAssignIn,
    TicketBulkIn,
    TicketCreate,
    TicketNote,
    TicketOut,
    TicketReply,
    TicketUpdate,
)
from app.services import service_ticket_service as S
from app.services.audit_service import audited, record_audit

router = APIRouter(prefix="/service-tickets", tags=["service_ticket"])


# ==================== 快捷回复（话术库）====================
# 注意：必须放在 /{ticket_id} 之前，避免 "quick-replies" 被当成 ticket_id。
@router.get("/quick-replies", response_model=list[QuickReplyOut])
async def list_quick_replies(
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> list[QuickReplyOut]:
    from sqlalchemy import select

    from app.models import ServiceTicketQuickReply

    rows = (await db.execute(
        select(ServiceTicketQuickReply).where(
            ServiceTicketQuickReply.tenant_id == user.tenant_id,
            ServiceTicketQuickReply.enabled.is_(True),
        ).order_by(ServiceTicketQuickReply.id.desc())
    )).scalars().all()
    return [QuickReplyOut.model_validate(r) for r in rows]


@router.post("/quick-replies", response_model=QuickReplyOut)
@audited("service_ticket.quick_reply_create", "quick_reply")
async def create_quick_reply(
    body: QuickReplyCreate,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> QuickReplyOut:
    from app.models import ServiceTicketQuickReply

    r = ServiceTicketQuickReply(
        tenant_id=user.tenant_id, title=body.title, content=body.content,
        category=body.category, scope=body.scope, enabled=body.enabled, created_by=user.id,
    )
    db.add(r)
    await db.flush()
    return QuickReplyOut.model_validate(r)


@router.patch("/quick-replies/{qr_id}", response_model=QuickReplyOut)
@audited("service_ticket.quick_reply_update", "quick_reply", id_arg="qr_id")
async def update_quick_reply(
    qr_id: int,
    body: QuickReplyUpdate,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> QuickReplyOut:
    from app.models import ServiceTicketQuickReply

    r = await db.get(ServiceTicketQuickReply, qr_id)
    if not r or r.tenant_id != user.tenant_id:
        raise NotFoundError("话术不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    await db.flush()
    return QuickReplyOut.model_validate(r)


@router.delete("/quick-replies/{qr_id}")
@audited("service_ticket.quick_reply_delete", "quick_reply", id_arg="qr_id")
async def delete_quick_reply(
    qr_id: int,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models import ServiceTicketQuickReply

    r = await db.get(ServiceTicketQuickReply, qr_id)
    if not r or r.tenant_id != user.tenant_id:
        raise NotFoundError("话术不存在")
    await db.delete(r)
    await db.flush()
    return {"message": "已删除"}


# ==================== 批量操作 ====================
@router.post("/bulk")
async def bulk_tickets(
    body: TicketBulkIn,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量操作工单：关单/解决/转派/改优先级/打标签/重开。"""
    from app.core.errors import ValidationError

    try:
        r = await S.bulk_update(db, tenant_id=user.tenant_id, ids=body.ids,
                                action=body.action, value=body.value)
    except ValueError as e:
        raise ValidationError(str(e))
    record_audit(
        db, action="service_ticket.bulk", resource_type="service_ticket", resource_id=None,
        after={"action": body.action, "ids": body.ids, "count": r["updated"], "value": body.value},
        tenant_id=user.tenant_id, actor_id=user.id, actor_type="user",
    )
    return r


@router.get("/channel-conversations")
async def list_channel_conversations(
    limit: int = 50,
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """渠道来源的会话列表（客服主管抽查/质检）。"""
    return await S.list_channel_conversations(db, tenant_id=user.tenant_id, limit=limit)


@router.patch("/channel-customers/{channel_user_id}/note")
async def set_customer_note(
    channel_user_id: int,
    body: TicketNote,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """设置渠道客户的备注（仅客服可见）。"""
    from app.core.errors import NotFoundError

    try:
        r = await S.set_customer_note(db, tenant_id=user.tenant_id, channel_user_id=channel_user_id, note=body.content)
    except ValueError:
        raise NotFoundError("客户不存在")
    await db.commit()
    return r


@router.get("/conversations/{conv_id}/messages")
async def conversation_messages(
    conv_id: int,
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """读取渠道会话的完整往来消息（含附件/图片）。"""
    from app.core.errors import NotFoundError

    try:
        return await S.conversation_messages(db, conversation_id=conv_id, tenant_id=user.tenant_id)
    except ValueError:
        raise NotFoundError("会话不存在")


@router.get("/conversations/{conv_id}/meta")
async def conversation_meta(
    conv_id: int,
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """渠道会话的备注与提醒开关（存在 conversation.settings）。"""
    from app.core.errors import NotFoundError
    from app.models import Conversation

    conv = await db.get(Conversation, conv_id)
    if not conv or conv.tenant_id != user.tenant_id:
        raise NotFoundError("会话不存在")
    st = conv.settings or {}
    return {"notes": st.get("_notes") or [], "watch": st.get("_watch", True)}


@router.post("/conversations/{conv_id}/notes")
async def add_conversation_note(
    conv_id: int,
    body: TicketNote,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """渠道会话内部备注（仅客服可见）。"""
    from app.core.errors import NotFoundError
    from app.models import Conversation

    conv = await db.get(Conversation, conv_id)
    if not conv or conv.tenant_id != user.tenant_id:
        raise NotFoundError("会话不存在")
    r = await S.add_conversation_note(db, conv, body.content, agent_id=user.id)
    await db.commit()
    return r


@router.patch("/conversations/{conv_id}/watch")
async def set_conversation_watch(
    conv_id: int,
    watch: bool = Query(...),
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """设置渠道会话的「有新回复通知我」开关。"""
    from app.core.errors import NotFoundError
    from app.models import Conversation

    conv = await db.get(Conversation, conv_id)
    if not conv or conv.tenant_id != user.tenant_id:
        raise NotFoundError("会话不存在")
    S.set_conversation_watch(conv, watch)
    await db.commit()
    return {"ok": True, "watch": watch}


@router.post("/conversations/{conv_id}/reply")
async def reply_in_conversation(
    conv_id: int,
    body: TicketReply,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """客服在渠道会话内回复：落库 + 回发客户渠道。"""
    from app.core.errors import NotFoundError
    from app.models import Conversation

    conv = await db.get(Conversation, conv_id)
    if not conv or conv.tenant_id != user.tenant_id:
        raise NotFoundError("会话不存在")
    r = await S.reply_in_conversation(db, conversation=conv, content=body.content, agent_id=user.id)
    await db.commit()
    return r


@router.post("/conversations/{conv_id}/attachment")
async def send_conversation_attachment(
    conv_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """客服在渠道会话内发送附件：落库展示 + 尽力回发渠道。"""
    import mimetypes
    from pathlib import Path as _P

    from app.core.errors import NotFoundError
    from app.ingest.storage import get_storage
    from app.models import Artifact, Conversation

    conv = await db.get(Conversation, conv_id)
    if not conv or conv.tenant_id != user.tenant_id:
        raise NotFoundError("会话不存在")

    filename = file.filename or "file"
    ext = _P(filename).suffix.lower().lstrip(".")
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    data = await file.read()
    file_key, chash = get_storage().save(tenant_id=user.tenant_id, filename=filename, data=data)

    if ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
        kind = "image"
    elif ext in ("mp4", "webm", "mov", "avi", "mkv", "mp3", "wav", "m4a"):
        kind = "video"
    else:
        kind = "document"

    db.add(Artifact(
        tenant_id=user.tenant_id, user_id=user.id, file_key=file_key, file_name=filename,
        file_ext=ext, mime=mime, size=len(data), source="upload", content_hash=chash,
    ))
    r = await S.send_attachment_in_conversation(
        db, conversation=conv, agent_id=user.id, file_key=file_key,
        name=filename, mime=mime, size=len(data), kind=kind,
    )
    await db.commit()
    return r


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    status: str | None = Query(None),
    assignee_id: int | None = Query(None),
    limit: int = 50,
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> list[TicketOut]:
    rows = await S.list_tickets(db, tenant_id=user.tenant_id, status=status,
                                assignee_id=assignee_id, limit=limit)
    return [TicketOut.model_validate(t) for t in rows]


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(
    ticket_id: int,
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    return TicketOut.model_validate(t)


@router.get("/{ticket_id}/context")
async def ticket_context(
    ticket_id: int,
    user: User = Depends(require_permission("service:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """客服工作台：该客户的上下文（历史工单 + 最近对话）。"""
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    return await S.customer_context(db, t)


@router.post("", response_model=TicketOut)
@audited("service_ticket.create", "service_ticket")
async def create_ticket(
    body: TicketCreate,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    t = await S.create_ticket(
        db, tenant_id=user.tenant_id, subject=body.subject, content=body.content,
        priority=body.priority, conversation_id=body.conversation_id,
        channel_id=body.channel_id, created_by=user.id, source="manual",
        category=body.category, tags=body.tags,
    )
    if body.assignee_id:
        t.assignee_id = body.assignee_id
    await db.commit()
    return TicketOut.model_validate(t)


@router.post("/{ticket_id}/notes", response_model=TicketOut)
async def add_note_endpoint(
    ticket_id: int,
    body: TicketNote,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    """追加内部备注（仅客服可见）。"""
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    await S.add_note(db, t, body.content, agent_id=user.id)
    await db.commit()
    return TicketOut.model_validate(t)


@router.post("/{ticket_id}/reply", response_model=TicketOut)
@audited("service_ticket.reply", "service_ticket", id_arg="ticket_id")
async def reply_ticket(
    ticket_id: int,
    body: TicketReply,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    await S.add_agent_reply(db, t, body.content, agent_id=user.id)
    await db.commit()
    return TicketOut.model_validate(t)


@router.post("/{ticket_id}/assign", response_model=TicketOut)
@audited("service_ticket.assign", "service_ticket", id_arg="ticket_id")
async def assign_ticket(
    ticket_id: int,
    body: TicketAssignIn,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    """转派工单给某个客服（assignee_id 传 null 表示取消指派）。"""
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    t.assignee_id = body.assignee_id
    await db.flush()
    await db.commit()
    return TicketOut.model_validate(t)


@router.post("/{ticket_id}/resolve", response_model=TicketOut)
@audited("service_ticket.resolve", "service_ticket", id_arg="ticket_id")
async def resolve_ticket(
    ticket_id: int,
    body: TicketNote | None = None,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    """标记工单为「已解决」（等待关闭/评价）。"""
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    await S.resolve_ticket(db, t, resolution=(body.content if body else None))
    await db.commit()
    return TicketOut.model_validate(t)


@router.patch("/{ticket_id}", response_model=TicketOut)
@audited("service_ticket.update", "service_ticket", id_arg="ticket_id")
async def update_ticket(
    ticket_id: int,
    body: TicketUpdate,
    user: User = Depends(require_permission("service:manage")),
    db: AsyncSession = Depends(get_db),
) -> TicketOut:
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("工单不存在")
    data = body.model_dump(exclude_unset=True)
    new_status = data.get("status")
    if new_status is not None and new_status not in ("open", "pending", "resolved", "closed"):
        from app.core.errors import ValidationError

        raise ValidationError(f"非法状态：{new_status}")
    if new_status == "closed":
        await S.close_ticket(db, t, resolution=data.get("resolution"))
        data.pop("status", None); data.pop("resolution", None)
    elif new_status == "resolved":
        await S.resolve_ticket(db, t, resolution=data.get("resolution"))
        data.pop("status", None); data.pop("resolution", None)
    for k, v in data.items():
        setattr(t, k, v)
    await db.flush()
    await db.commit()
    return TicketOut.model_validate(t)
