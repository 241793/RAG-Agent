"""系统设置接口：查看/更新配置、重启服务（管理员）。

覆盖原本需手改 .env 的配置：保存即热生效；标 restart 的项需重启进程。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.middleware.auth_dep import require_permission
from app.models import User
from app.services import settings_service
from app.services.audit_service import audited

router = APIRouter(prefix="/system/settings", tags=["settings"])


class SettingsUpdateIn(BaseModel):
    updates: dict


@router.get("")
async def get_settings(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    return {
        "groups": settings_service.groups(),
        "fields": settings_service.get_config(),
    }


@router.put("")
@audited("system.settings_update", "system_setting")
async def update_settings(
    body: SettingsUpdateIn,
    user: User = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    r = await settings_service.update_config(db, user_id=user.id, updates=body.updates or {})
    return {"message": "已保存", **r}


@router.post("/restart")
async def restart_service(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """重启后端进程，使启动期读取的配置生效。响应返回后延迟触发。"""
    import asyncio

    async def _do_restart() -> None:
        await asyncio.sleep(0.8)
        _restart_process()

    asyncio.get_running_loop().create_task(_do_restart())
    return {"message": "服务正在重启，请稍候刷新页面"}


def _restart_process() -> None:
    """重启当前进程（源码态用 uvicorn 重拉；冻结态重新执行自身）。"""
    import os
    import sys

    from app.core.config import settings
    from app.core.logging import get_logger

    log = get_logger("settings")
    try:
        # 清理长驻子进程
        import asyncio

        from app.channels.manager import channel_manager
        from app.services.mcp_manager import mcp_manager

        async def _cleanup() -> None:
            try:
                await channel_manager.stop_all()
            except Exception:  # noqa: BLE001
                pass
            try:
                await mcp_manager.stop_all()
            except Exception:  # noqa: BLE001
                pass

        try:
            asyncio.run(_cleanup())
        except RuntimeError:
            pass
    except Exception:  # noqa: BLE001
        pass

    port = str(settings.port)
    host = os.environ.get("RAG_HOST", "0.0.0.0")
    log.info("service_restart", port=port)
    if getattr(sys, "frozen", False):
        os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
    else:
        os.execv(
            sys.executable,
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", port],
        )
