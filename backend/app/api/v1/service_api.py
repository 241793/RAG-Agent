"""客服对外网关 API：供外部系统（第三方客服台/自研 App/跨境平台）通过 API Key 建单/查单/追加消息。

鉴权：X-API-Key（复用 auth_dep.get_apikey_auth），需 scope service:submit / service:read。
API Key 的 user_id 映射为 external 客户主体；建立的工单归属该客户，不泄露内部数据。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, PermissionDeniedError
from app.middleware.auth_dep import ApiKeyAuth, get_apikey_auth
from app.services import service_ticket_service as S

router = APIRouter(prefix="/service-gateway", tags=["service_gateway"])


class GatewayTicketIn(BaseModel):
    external_user: str = Field(min_length=1, description="外部客户标识（如第三方系统里的用户 id）")
    subject: str = Field(min_length=1, max_length=512)
    content: str = ""
    priority: str = "normal"  # low/normal/high/urgent
    category: str | None = None
    channel_kind: str | None = None  # 渠道来源标识（如 whatsapp/tiktok）
    customer_lang: str | None = None
    channel_id: int | None = None  # 若复用已接入的外部渠道（回发用）


class GatewayMessageIn(BaseModel):
    content: str = Field(min_length=1)
    role: str = "user"  # user（客户）/ agent（客服台代答）


def _require_scope(auth: ApiKeyAuth, code: str) -> None:
    if not auth.has_scope(code):
        raise PermissionDeniedError(f"缺少 scope: {code}")


@router.post("/tickets")
async def gateway_create_ticket(
    body: GatewayTicketIn,
    auth: ApiKeyAuth = Depends(get_apikey_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """外部系统建工单。工单归属该 API Key 绑定的客户主体。"""
    _require_scope(auth, "service:submit")
    tenant_id = auth.key.tenant_id
    t = await S.create_ticket(
        db, tenant_id=tenant_id, subject=body.subject, content=body.content,
        channel_id=body.channel_id, channel_kind=body.channel_kind,
        external_user=body.external_user, priority=body.priority,
        category=body.category, customer_lang=body.customer_lang,
        created_by=auth.key.user_id, source="api",
    )
    await db.commit()
    return {"id": t.id, "status": t.status, "sla_due_at": t.sla_due_at,
            "created_at": t.created_at}


@router.get("/tickets")
async def gateway_list_tickets(
    external_user: str | None = Query(None),
    limit: int = 50,
    auth: ApiKeyAuth = Depends(get_apikey_auth),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """查工单。仅在指定 external_user 时返回其工单（防跨客户窥探）。"""
    _require_scope(auth, "service:read")
    if not external_user:
        raise PermissionDeniedError("必须提供 external_user")
    from app.models import ServiceTicket

    rows = (await db.execute(
        select(ServiceTicket).where(
            ServiceTicket.tenant_id == auth.key.tenant_id,
            ServiceTicket.external_user == external_user,
        ).order_by(ServiceTicket.id.desc()).limit(min(limit, 100))
    )).scalars().all()
    return [{"id": t.id, "subject": t.subject, "status": t.status, "priority": t.priority,
             "satisfaction": t.satisfaction, "created_at": t.created_at} for t in rows]


@router.get("/tickets/{ticket_id}")
async def gateway_get_ticket(
    ticket_id: int,
    auth: ApiKeyAuth = Depends(get_apikey_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_scope(auth, "service:read")
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != auth.key.tenant_id:
        raise NotFoundError("工单不存在")
    return {"id": t.id, "subject": t.subject, "status": t.status, "priority": t.priority,
            "category": t.category, "messages": t.messages,
            "sla_due_at": t.sla_due_at, "sla_breached": t.sla_breached,
            "satisfaction": t.satisfaction, "customer_lang": t.customer_lang}


@router.post("/tickets/{ticket_id}/messages")
async def gateway_add_message(
    ticket_id: int,
    body: GatewayMessageIn,
    auth: ApiKeyAuth = Depends(get_apikey_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """外部系统追加消息：role=user 走客户消息，role=agent 走客服回复（回发渠道）。"""
    _require_scope(auth, "service:submit")
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != auth.key.tenant_id:
        raise NotFoundError("工单不存在")
    if body.role == "agent":
        r = await S.add_agent_reply(db, t, body.content, agent_id=auth.key.user_id or 0)
        await db.commit()
        return {"ok": True, "sent_to_channel": r.get("sent_to_channel")}
    await S.add_user_message(db, t, body.content)
    await db.commit()
    return {"ok": True}


@router.post("/tickets/{ticket_id}/rate")
async def gateway_rate_ticket(
    ticket_id: int,
    score: int = Query(..., ge=1, le=5),
    comment: str | None = Query(None),
    auth: ApiKeyAuth = Depends(get_apikey_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """客户满意度评价（1-5）。"""
    _require_scope(auth, "service:submit")
    from app.models import ServiceTicket

    t = await db.get(ServiceTicket, ticket_id)
    if not t or t.tenant_id != auth.key.tenant_id:
        raise NotFoundError("工单不存在")
    await S.rate_ticket(db, t, score, comment)
    await db.commit()
    return {"ok": True, "satisfaction": t.satisfaction}
