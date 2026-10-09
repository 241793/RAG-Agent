"""站内消息通知接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.middleware.auth_dep import get_current_user
from app.models import Notification, User

router = APIRouter(prefix="/notifications", tags=["notification"])


@router.get("")
async def list_notifications(
    page: int = 1,
    page_size: int = 20,
    unread_only: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    base = select(Notification).where(Notification.user_id == user.id, Notification.tenant_id == user.tenant_id)
    if unread_only:
        base = base.where(Notification.read.is_(False))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    unread = (
        await db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user.id, Notification.read.is_(False)
            )
        )
    ).scalar_one()
    return {
        "total": total,
        "unread": unread,
        "items": [
            {
                "id": n.id, "kind": n.kind, "title": n.title, "body": n.body,
                "level": n.level, "link": n.link, "read": n.read,
                "ref_type": n.ref_type, "ref_id": n.ref_id,
                "created_at": int(n.created_at.timestamp() * 1000) if n.created_at else 0,
            }
            for n in rows
        ],
    }


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    n = (
        await db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user.id, Notification.read.is_(False)
            )
        )
    ).scalar_one()
    return {"unread": int(n)}


@router.post("/read")
async def mark_read(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ids = body.get("ids") or []
    if not ids:
        return {"message": "无操作"}
    await db.execute(
        update(Notification)
        .where(Notification.id.in_(ids), Notification.user_id == user.id)
        .values(read=True)
    )
    await db.flush()
    return {"message": "已标记已读"}


@router.post("/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.read.is_(False)).values(read=True)
    )
    await db.flush()
    return {"message": "已全部标记已读"}


@router.delete("/{notif_id}")
async def delete_notification(
    notif_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    n = await db.get(Notification, notif_id)
    if n and n.user_id == user.id:
        await db.delete(n)
        await db.flush()
    return {"message": "已删除"}
