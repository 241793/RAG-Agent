"""系统运行日志查看（管理员）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.errors import ValidationError
from app.middleware.auth_dep import require_permission
from app.models import User

router = APIRouter(prefix="/system", tags=["system"])

_MAX_BYTES = 512 * 1024  # 单次读取上限


def _log_path() -> Path:
    if not settings.log_file:
        raise ValidationError("未配置日志文件（settings.log_file 为空）")
    return Path(settings.log_file).resolve()


@router.get("/logs")
async def read_logs(
    lines: int = 300,
    level: str | None = None,
    keyword: str | None = None,
    user: User = Depends(require_permission("system:read")),
) -> dict:
    """返回最近 N 行日志，可按级别/关键字过滤。文件不存在返回空。"""
    p = _log_path()
    # 也接受轮转的 .1/.2（读当前主文件；若为空则尝试最近备份）
    candidates = [p] + [p.with_name(p.name + f".{i}") for i in range(1, settings.log_backup_count + 1)]
    content = ""
    used = None
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            used = c
            break
    if used is None:
        return {"lines": [], "path": str(p), "total": 0}

    size = used.stat().st_size
    with used.open("rb") as f:
        if size > _MAX_BYTES:
            f.seek(size - _MAX_BYTES)
            f.readline()  # 丢弃可能被截断的首行
        content = f.read().decode("utf-8", errors="replace")

    all_lines = content.splitlines()
    lines = max(1, min(lines, 2000))
    picked = all_lines[-lines:]

    if level:
        lv = level.lower()
        picked = [ln for ln in picked if f'"level": "{lv}"' in ln or lv.upper() in ln.upper()[:40]]
    if keyword:
        picked = [ln for ln in picked if keyword in ln]

    return {"lines": picked, "path": str(used), "total": len(picked)}


@router.get("/logs/download")
async def download_logs(
    user: User = Depends(require_permission("system:read")),
):
    from fastapi.responses import FileResponse

    p = _log_path()
    if not p.exists():
        raise ValidationError("日志文件不存在")
    return FileResponse(str(p), filename=p.name, media_type="text/plain")


@router.get("/logs/stats")
async def log_stats(
    user: User = Depends(require_permission("system:read")),
) -> dict:
    """日志文件大小/备份数/保留策略，供前端展示与清理判断。"""
    p = _log_path()
    files = [p] + [p.with_name(p.name + f".{i}") for i in range(1, settings.log_backup_count + 1)]
    total = 0
    count = 0
    for f in files:
        if f.exists():
            total += f.stat().st_size
            count += 1
    return {
        "path": str(p),
        "total_bytes": total,
        "file_count": count,
        "max_bytes": settings.log_max_bytes,
        "backup_count": settings.log_backup_count,
        "retention_days": settings.log_retention_days,
        "cleanup_interval_hours": settings.log_cleanup_interval_hours,
    }


@router.post("/logs/clear")
async def clear_logs(
    user: User = Depends(require_permission("system:write")),
) -> dict:
    """清空当前日志（截断，因文件被 handler 占用）+ 删除所有轮转备份。"""
    p = _log_path()
    backups = [p.with_name(p.name + f".{i}") for i in range(1, settings.log_backup_count + 1)]
    removed = 0
    freed = 0
    # 删除备份
    for f in backups:
        if f.exists():
            try:
                freed += f.stat().st_size
                f.unlink()
                removed += 1
            except Exception:  # noqa: BLE001
                pass
    # 截断主文件（不删除，避免与 RotatingFileHandler 冲突）
    if p.exists():
        try:
            freed += p.stat().st_size
            with p.open("w", encoding="utf-8"):
                pass
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    return {"message": f"已清理 {removed} 个日志文件", "removed": removed, "freed_bytes": freed}
