"""更新接口：检查新版本（管理员）。

仅做「检查 + 回报」，不做下载与换盘 —— 那部分在桌面版由 Electron 与外部脚本协同完成。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.middleware.auth_dep import require_permission
from app.models import User
from app.services import update_service

router = APIRouter(prefix="/system/update", tags=["update"])


@router.get("/check")
async def check_update(
    force: bool = False,
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """检查是否有新版本。

    永不返回 5xx：离线/限流/超时一律以 `ok=False` + `error` 表达，便于前端稳定展示。
    默认走 15 分钟缓存；`?force=true` 强制刷新。
    """
    return await update_service.check_update(force=force)
