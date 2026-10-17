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
    if deployment not in ("desktop", "docker", "source"):
        return {"ok": False, "error": f"当前为 {deployment} 部署，不支持应用内更新"}

    info = await update_service.check_update(force=True)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error") or "检查更新失败"}
    if not info.get("update_available"):
        return {"ok": False, "error": "已是最新版本"}
    asset = info.get("asset") or {}
    url = asset.get("url")
    if not url:
        kind = "win-x64.zip" if deployment == "desktop" else "docker.zip"
        return {"ok": False, "error": f"该 Release 未提供适配的更新包（{kind}）"}

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

    if deployment in ("docker", "source"):
        # Docker / 源码：不写换盘脚本。Docker 由容器内看门狗覆盖 /app 后退出，
        # 由 compose 拉起；源码由 apply 接口直接覆盖并 os.execv 重启。
        import json

        from app.core.config import BASE_DIR

        upd = BASE_DIR / "updates"
        upd.mkdir(parents=True, exist_ok=True)
        (upd / "pending.json").write_text(
            json.dumps({"version": version, "staging": ex["staging"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "version": version,
            "verified": r.get("verified", False),
            "size": r.get("size", 0),
            "message": (
                "更新包已下载并校验，点击「重启并应用」后容器将自动覆盖并重启"
                if deployment == "docker"
                else "更新包已下载并校验，点击「重启并应用」后服务将覆盖文件并自动重启"
            ),
        }

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
    """写应用信号：桌面版由 Electron 换盘；Docker 由容器内看门狗覆盖源码后退出重启。"""
    import json

    from app.core.config import BASE_DIR
    from app.core.logging import get_logger

    deployment = update_service.detect_deployment()
    log = get_logger("update")

    if deployment == "docker":
        upd = BASE_DIR / "updates"
        pending = upd / "pending.json"
        if not pending.is_file():
            return {"ok": False, "error": "未找到已下载的更新包，请先点击「立即更新」"}
        try:
            info = json.loads(pending.read_text(encoding="utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "更新状态文件损坏，请重新下载"}
        (upd / "apply.requested").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8"
        )
        pending.unlink(missing_ok=True)
        log.info("docker_update_requested", version=info.get("version"), by=user.id)
        return {
            "ok": True,
            "message": "正在应用更新：容器将在数秒内覆盖源码并自动重启，请稍候刷新页面",
        }

    if deployment == "source":
        # 源码态：直接覆盖项目目录，然后 os.execv 原地重启。
        # 覆盖是同步的（可能要 pip install 几十秒），故放到线程里跑，避免阻塞事件循环。
        import asyncio
        import json
        from pathlib import Path

        from app.core.config import BASE_DIR
        from app.services import source_update

        upd = BASE_DIR / "updates"
        pending = upd / "pending.json"
        if not pending.is_file():
            return {"ok": False, "error": "未找到已下载的更新包，请先点击「立即更新」"}
        try:
            info = json.loads(pending.read_text(encoding="utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "更新状态文件损坏，请重新下载"}

        staging = Path(str(info.get("staging") or ""))
        version = str(info.get("version") or "")
        if not staging.is_dir():
            return {"ok": False, "error": "暂存目录不存在，请重新下载"}

        result = await asyncio.to_thread(source_update.apply_package, staging, version)
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error") or "应用更新失败"}

        pending.unlink(missing_ok=True)
        log.info("source_update_applied", version=version, by=user.id)

        # 延迟重启：先让响应返回，再 execv
        async def _restart() -> None:
            await asyncio.sleep(1.0)
            source_update.restart_process()

        asyncio.get_running_loop().create_task(_restart())
        return {
            "ok": True,
            "message": "更新已应用，服务正在重启，请稍候刷新页面（约 10 秒）",
        }

    if deployment != "desktop":
        return {"ok": False, "error": f"当前为 {deployment} 部署，不支持应用内更新"}

    sig = update_service.write_apply_signal()
    log.info("update_apply_requested", signal=sig, by=user.id)
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
