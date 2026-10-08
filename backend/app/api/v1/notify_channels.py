"""通知渠道管理接口：配置站内/Webhook/企业微信/钉钉/邮件等通知出口。

config 内敏感字段（password/secret/token/api_key）加密存储、读取脱敏。
定时任务等业务通过 notifiers.registry.dispatch 派发到这些渠道。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt, mask
from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import NotifyChannel, User
from app.notifiers.base import NotificationMessage
from app.notifiers.registry import build_notifier
from app.schemas.notify_channel import (
    NotifyChannelCreate,
    NotifyChannelOut,
    NotifyChannelUpdate,
)
from app.services.audit_service import audited

router = APIRouter(prefix="/notify-channels", tags=["notify_channel"])

_SECRET_HINTS = ("password", "secret", "token", "api_key", "key")


def _is_secret_key(k: str) -> bool:
    return any(h in k.lower() for h in _SECRET_HINTS)


def _encrypt_config(cfg: dict | None) -> dict | None:
    if not cfg:
        return cfg
    out = dict(cfg)
    for k, v in list(out.items()):
        if _is_secret_key(k) and isinstance(v, str) and v and not v.startswith("enc:"):
            out[k] = encrypt(v)
    return out


def _mask_config(cfg: dict | None) -> dict | None:
    if not cfg:
        return cfg
    out = dict(cfg)
    for k, v in list(out.items()):
        if _is_secret_key(k) and v:
            out[k] = mask(v) if isinstance(v, str) else v
            out[f"{k}_set"] = True
    return out


def _to_out(c: NotifyChannel) -> NotifyChannelOut:
    return NotifyChannelOut(
        id=c.id, kind=c.kind, name=c.name, config=_mask_config(c.config),
        enabled=c.enabled, events=c.events,
    )


@router.get("", response_model=list[NotifyChannelOut])
async def list_channels(
    user: User = Depends(require_permission("notify:read")),
    db: AsyncSession = Depends(get_db),
) -> list[NotifyChannelOut]:
    rows = (
        await db.execute(
            select(NotifyChannel).where(NotifyChannel.tenant_id == user.tenant_id).order_by(NotifyChannel.id.desc())
        )
    ).scalars().all()
    return [_to_out(c) for c in rows]


@router.post("", response_model=NotifyChannelOut)
@audited("notify_channel.create", "notify_channel")
async def create_channel(
    body: NotifyChannelCreate,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> NotifyChannelOut:
    if body.kind not in ("inapp", "webhook", "wecom", "dingtalk", "smtp", "external"):
        raise ValidationError("不支持的通知渠道类型")
    c = NotifyChannel(
        tenant_id=user.tenant_id, kind=body.kind, name=body.name,
        config=_encrypt_config(body.config), enabled=body.enabled, events=body.events,
    )
    db.add(c)
    await db.flush()
    return _to_out(c)


@router.patch("/{channel_id}", response_model=NotifyChannelOut)
@audited("notify_channel.update", "notify_channel", id_arg="channel_id")
async def update_channel(
    channel_id: int,
    body: NotifyChannelUpdate,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> NotifyChannelOut:
    c = await db.get(NotifyChannel, channel_id)
    if not c or c.tenant_id != user.tenant_id:
        raise NotFoundError("通知渠道不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k == "config":
            merged = {**(c.config or {}), **(v or {})}
            c.config = _encrypt_config(merged)
        else:
            setattr(c, k, v)
    await db.flush()
    return _to_out(c)


@router.delete("/{channel_id}")
@audited("notify_channel.delete", "notify_channel", id_arg="channel_id")
async def delete_channel(
    channel_id: int,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    c = await db.get(NotifyChannel, channel_id)
    if not c or c.tenant_id != user.tenant_id:
        raise NotFoundError("通知渠道不存在")
    await db.delete(c)
    await db.flush()
    return {"message": "已删除"}


@router.post("/{channel_id}/test")
async def test_channel(
    channel_id: int,
    user: User = Depends(require_permission("notify:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发一条测试通知。inapp 渠道需指定收件人（默认当前用户）。"""
    c = await db.get(NotifyChannel, channel_id)
    if not c or c.tenant_id != user.tenant_id:
        raise NotFoundError("通知渠道不存在")
    cfg = dict(c.config or {})
    if c.kind == "inapp":
        cfg.setdefault("user_id", user.id)
    try:
        ch = build_notifier(c.kind, tenant_id=user.tenant_id, config=cfg)
        ok = await ch.send(NotificationMessage(
            title="测试通知", body="这是一条来自 RAG 知识库平台的测试通知。",
            level="info", kind="system", user_id=user.id,
        ))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}
    return {"ok": bool(ok), "message": "已发送" if ok else "发送失败（配置可能不完整）"}
