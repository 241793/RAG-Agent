"""事件订阅接口：外部系统订阅平台事件，平台在事件发生时 POST 回调。

权限沿用 notify:read / notify:manage。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import require_permission
from app.models import EventSubscription, User
from app.schemas.event_subscription import EventSubCreate, EventSubOut, EventSubUpdate
from app.services.audit_service import audited

router = APIRouter(prefix="/event-subscriptions", tags=["event_subscription"])


def _to_out(s: EventSubscription) -> EventSubOut:
    return EventSubOut(
        id=s.id, name=s.name, url=s.url, events=s.events,
        secret_set=bool(s.secret), enabled=s.enabled,
    )


@router.get("/events")
async def list_events(
    user: User = Depends(require_permission("notify:read")),
) -> list[str]:
    """平台可订阅的事件清单（供前端下拉）。"""
    from app.services.event_subscription_service import KNOWN_EVENTS

    return KNOWN_EVENTS


@router.get("", response_model=list[EventSubOut])
async def list_subscriptions(
    user: User = Depends(require_permission("notify:read")),
    db: AsyncSession = Depends(get_db),
) -> list[EventSubOut]:
    rows = (await db.execute(
        select(EventSubscription).where(EventSubscription.tenant_id == user.tenant_id)
        .order_by(EventSubscription.id.desc())
    )).scalars().all()
    return [_to_out(s) for s in rows]


@router.post("", response_model=EventSubOut)
@audited("event_subscription.create", "event_subscription")
async def create_subscription(
    body: EventSubCreate,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> EventSubOut:
    s = EventSubscription(
        tenant_id=user.tenant_id, name=body.name, url=body.url,
        events=body.events, enabled=body.enabled,
        secret=(encrypt(body.secret) if body.secret else None),
        created_by=user.id,
    )
    db.add(s)
    await db.flush()
    return _to_out(s)


@router.patch("/{sub_id}", response_model=EventSubOut)
@audited("event_subscription.update", "event_subscription", id_arg="sub_id")
async def update_subscription(
    sub_id: int,
    body: EventSubUpdate,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> EventSubOut:
    s = await db.get(EventSubscription, sub_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("事件订阅不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "secret":
            if v:  # 留空/掩码表示不改
                s.secret = encrypt(v)
        else:
            setattr(s, k, v)
    await db.flush()
    return _to_out(s)


@router.delete("/{sub_id}")
@audited("event_subscription.delete", "event_subscription", id_arg="sub_id")
async def delete_subscription(
    sub_id: int,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    s = await db.get(EventSubscription, sub_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("事件订阅不存在")
    await db.delete(s)
    await db.flush()
    return {"message": "已删除"}


@router.post("/{sub_id}/test")
async def test_subscription(
    sub_id: int,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """向该订阅方发送一条测试事件。"""
    from app.core.crypto import decrypt as _decrypt
    from app.services.event_subscription_service import _deliver

    s = await db.get(EventSubscription, sub_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("事件订阅不存在")
    secret = None
    if s.secret:
        secret = _decrypt(s.secret) if s.secret.startswith("enc:") else s.secret
    ok = await _deliver(s.url, secret, "event.test",
                        {"message": "这是一条来自 RAG 知识库平台的测试事件"}, user.tenant_id)
    return {"ok": ok, "message": "已送达" if ok else "投递失败（URL 不可达或返回错误）"}
