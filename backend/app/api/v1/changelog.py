"""更新日志接口（所有已登录用户可读）。

门用 `chat:use` 而非 `system:manage` —— 更新日志面向全体用户展示，
而 `viewer`（默认普通用户角色）持有的正是 `chat:use`。

刻意不复用 `/system/update/check`：那个全程管理员权限，且会请求 GitHub，
非管理员或离线环境必然拿不到内容。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.middleware.auth_dep import require_permission
from app.models import User
from app.services import changelog_service

router = APIRouter(prefix="/changelog", tags=["changelog"])


@router.get("")
async def get_changelog(
    force: bool = False,
    user: User = Depends(require_permission("chat:use")),
) -> dict:
    """获取更新日志（本地 CHANGELOG.md 优先，GitHub Release 兜底）。

    永不返回 5xx：读不到内容时 `source="none"` + 空列表，前端据此隐藏滚动条。
    """
    return await changelog_service.get_changelog(force=force)
