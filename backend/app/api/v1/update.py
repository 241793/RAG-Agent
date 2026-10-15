"""更新接口：检查 / 下载 / 查询进度 / 应用（管理员）。

分工：
- 本模块负责 下载 → 校验 → 解压到暂存区 → 写信号文件
- **换盘由应用退出后的外部脚本执行**（Windows 不允许覆盖运行中的 exe）
- Electron 主进程轮询信号文件，退出应用并拉起 `apply_update.bat`

所有端点永不返回 5xx：失败一律以 `ok=False` + `error` 表达。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.middleware.auth_dep import require_permission
from app.models import User
from app.services import update_service
from app.services.audit_service import audited

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


@router.post("/download")
async def download_update(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """下载最新版更新包并校验 sha256（仅桌面版）。

    只接受服务端自己查到的资产地址 —— 不接受前端传入 URL，
    避免被诱导下载任意文件（SSRF / 供应链）。
    """
    deployment = update_service.detect_deployment()
    if deployment != "desktop":
        return {"ok": False, "error": "仅桌面版支持应用内更新；当前为 "
                                      f"{deployment} 部署，请用相应命令升级"}

    info = await update_service.check_update(force=True)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "检查更新失败"}
    if not info.get("update_available"):
        return {"ok": False, "error": "已是最新版本"}
    asset = info.get("asset") or {}
    url = asset.get("url")
    if not url:
        return {"ok": False, "error": "该 Release 未提供桌面版更新包（win-x64.zip）"}

    version = info.get("latest") or ""
    # 版本号白名单校验：进入下载/解压/换盘链路的版本号必须是纯数字点分格式，
    # 防止后续被拼进路径或脚本参数（路径穿越 / 命令注入）。
    if not update_service.is_safe_version(version):
        return {"ok": False, "error": f"版本号格式非法，已拒绝：{version[:32]}"}

    r = await update_service.download_update(url=url, digest=asset.get("digest"), version=version)
    if not r.get("ok"):
        return r

    ex = update_service.extract_update(zip_path=r["path"], version=version)
    if not ex.get("ok"):
        return ex

    script = update_service.write_apply_script()
    update_service.write_pending(
        version=version, staging_dir=ex["staging"], script_path=script
    )
    return {
        "ok": True,
        "version": version,
        "verified": r.get("verified", False),
        "size": r.get("size", 0),
        "message": "更新包已下载并校验完成，点击「重启并应用」生效",
    }


@router.get("/progress")
async def download_progress(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """查询下载/解压进度（前端轮询）。"""
    return update_service.get_progress()


@router.post("/apply")
@audited("system.update_apply", "system")
async def apply_update(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """写换盘信号：Electron 收到后退出应用并执行换盘脚本。"""
    deployment = update_service.detect_deployment()
    if deployment != "desktop":
        return {"ok": False, "error": "仅桌面版支持应用内更新"}

    sig = update_service.write_apply_signal()
    from app.core.logging import get_logger

    get_logger("update").info("update_apply_requested", signal=sig, by=user.id)
    return {
        "ok": True,
        "message": "正在重启并应用更新，应用将短暂关闭后自动启动……",
    }


class CancelIn(BaseModel):
    pass


@router.post("/cancel")
async def cancel_update(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """清除待应用状态与暂存文件（放弃本次更新）。"""
    update_service.reset_progress()
    return {"ok": True, "message": "已取消"}
