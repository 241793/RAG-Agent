"""入站 Webhook：外部系统 POST /hooks/{token} 触发指定定时任务。"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, PermissionDeniedError
from app.middleware.auth_dep import require_permission
from app.models import ScheduledTask, User, WebhookToken

router = APIRouter(tags=["webhook"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post("/scheduled-tasks/{task_id}/webhook-token")
async def create_webhook_token(
    task_id: int,
    body: dict,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """为定时任务生成入站 Webhook 令牌（明文仅本次返回）。"""
    t = await db.get(ScheduledTask, task_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("定时任务不存在")
    plain = secrets.token_urlsafe(24)
    tok = WebhookToken(
        tenant_id=user.tenant_id, task_id=task_id,
        token_hash=_hash(plain), name=(body or {}).get("name") or "默认",
    )
    db.add(tok)
    await db.flush()
    return {"id": tok.id, "token": plain, "webhook_url": f"/api/v1/hooks/{plain}",
            "message": "请妥善保存 token，仅显示一次"}


@router.get("/scheduled-tasks/{task_id}/webhook-tokens")
async def list_webhook_tokens(
    task_id: int,
    user: User = Depends(require_permission("schedule:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    t = await db.get(ScheduledTask, task_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("定时任务不存在")
    rows = (await db.execute(select(WebhookToken).where(WebhookToken.task_id == task_id))).scalars().all()
    return [{"id": r.id, "name": r.name, "enabled": r.enabled, "created_at": r.created_at} for r in rows]


@router.delete("/webhook-tokens/{token_id}")
async def delete_webhook_token(
    token_id: int,
    user: User = Depends(require_permission("schedule:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tk = await db.get(WebhookToken, token_id)
    if tk and tk.tenant_id == user.tenant_id:
        await db.delete(tk)
        await db.flush()
    return {"message": "已删除"}


# ---- 公开入站端点（token 鉴权，无需登录）----
@router.post("/hooks/{token}")
async def invoke_webhook(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """外部系统调用：按 token 找到任务并触发一次执行。请求体作为 inputs 注入。"""
    import asyncio

    from app.tasks.scheduler_tasks import execute_task

    tk = (
        await db.execute(select(WebhookToken).where(WebhookToken.token_hash == _hash(token)))
    ).scalar_one_or_none()
    if not tk or not tk.enabled:
        raise PermissionDeniedError("无效的 Webhook 令牌")
    t = await db.get(ScheduledTask, tk.task_id)
    if not t or not t.enabled:
        raise NotFoundError("目标任务不存在或已禁用")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    # 载荷注入到任务输入（供工作流/提示词使用）
    if isinstance(payload, dict) and payload:
        t.inputs = {**(t.inputs or {}), "_webhook": payload}
        await db.flush()

    asyncio.create_task(execute_task(t.id, manual=True))
    return {"message": "已触发", "task_id": t.id}
