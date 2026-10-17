"""源码运行的在线更新：用下载的源码包覆盖项目目录，然后 os.execv 自重启用。

与其它形态的差异
----------------
- 桌面版：换的是安装目录里的 exe，由外部 bat 在进程退出后执行；
- Docker：换的是挂载目录 /app，覆盖后退出，由 compose 拉起；
- **源码态**：直接覆盖项目目录（backend/ 与 web/dist/），
  然后用 `os.execv` 原地重启进程（复用 settings._restart_process 的思路）。

安全约束
--------
只覆盖代码与前端产物，**绝不动** data/（数据库、上传文件）、.env、.venv。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.config import BASE_DIR, RESOURCE_DIR
from app.core.logging import get_logger

logger = get_logger("source_update")

# 覆盖目标（相对项目根）：只替换代码与前端产物
TARGETS = ("backend", "web/dist")
# 允许覆盖时排除的目录名（数据与虚拟环境必须保留）
EXCLUDE = {"data", ".venv", "__pycache__", ".pytest_cache", "updates", ".git"}


def _project_root() -> Path:
    """项目根（含 backend/ 与 web/）。"""
    return RESOURCE_DIR


def _backup_root() -> Path:
    d = BASE_DIR / "updates" / "backup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_over(src: Path, dst: Path) -> None:
    """把 src 覆盖进 dst，但跳过 EXCLUDE 里的条目。"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in EXCLUDE:
            continue
        target = dst / item.name
        if item.is_dir():
            # 递归复制，保留目标已有的 excluded 目录
            _copy_over(item, target)
        else:
            shutil.copy2(item, target)


def validate_package(staging: Path) -> str | None:
    """校验包结构。返回错误信息，None 表示通过。"""
    if not (staging / "backend" / "app" / "main.py").is_file():
        return "更新包结构异常：缺少 backend/app/main.py"
    if not (staging / "web" / "dist" / "index.html").is_file():
        return "更新包结构异常：缺少 web/dist/index.html"
    return None


def backup_current(version: str) -> Path:
    """备份将被覆盖的目录（backend 与 web/dist）。"""
    import time

    root = _project_root()
    base = _backup_root() / f"source-{version}-{int(time.time())}"
    dest = base
    n = 1
    while dest.exists():
        dest = base.with_name(f"{base.name}-{n}")
        n += 1
    dest.mkdir(parents=True, exist_ok=True)
    for rel in TARGETS:
        src = root / rel
        if not src.exists():
            continue
        tgt = dest / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, tgt, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*EXCLUDE))
    logger.info("source_update_backup", path=str(dest))
    return dest


def restore_backup(backup_dir: Path) -> None:
    root = _project_root()
    for rel in TARGETS:
        src = backup_dir / rel
        if src.exists():
            _copy_over(src, root / rel)
    logger.warning("source_update_restored", path=str(backup_dir))


def apply_package(staging: Path, version: str) -> dict:
    """覆盖项目目录。返回 {"ok", "error"?}。不负责重启。"""
    err = validate_package(staging)
    if err:
        return {"ok": False, "error": err}

    root = _project_root()
    backup = None
    try:
        backup = backup_current(version)

        logger.info("source_update_copy", version=version)
        _copy_over(staging / "backend", root / "backend")
        _copy_over(staging / "web" / "dist", root / "web" / "dist")

        # 更新日志（供 changelog_service 读 RESOURCE_DIR）
        cl = staging / "CHANGELOG.md"
        if cl.is_file():
            shutil.copy2(cl, root / "CHANGELOG.md")

        # 依赖可能有变化：装一次（无变化时 pip 很快跳过）
        req = root / "backend" / "requirements.txt"
        if req.is_file():
            try:
                import sys

                proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", str(req)],
                    capture_output=True, text=True, timeout=600,
                )
                if proc.returncode != 0:
                    msg = (proc.stderr or proc.stdout or "")[-300:]
                    logger.error("source_update_pip_failed", rc=proc.returncode)
                    restore_backup(backup)
                    return {"ok": False, "error": f"依赖安装失败，已回滚：{msg[:200]}"}
            except Exception as e:  # noqa: BLE001
                logger.exception("source_update_pip_exception")
                restore_backup(backup)
                return {"ok": False, "error": f"依赖安装异常，已回滚：{str(e)[:200]}"}

        logger.info("source_update_applied", version=version)
        return {"ok": True, "backup": str(backup)}
    except Exception as e:  # noqa: BLE001
        logger.exception("source_update_apply_failed")
        if backup:
            restore_backup(backup)
        return {"ok": False, "error": f"覆盖失败，已回滚：{str(e)[:200]}"}


def restart_process() -> None:
    """原地重启：重新执行 Python 启动 uvicorn（与 settings._restart_process 一致）。"""
    import asyncio
    import os
    import sys

    from app.core.config import settings
    from app.core.logging import get_logger as _gl

    log = _gl("source_update")

    # 清理长驻子进程（渠道 / MCP），避免端口与连接泄漏
    try:
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

    host = os.environ.get("RAG_HOST", "0.0.0.0")
    port = str(settings.port)
    log.warning("source_update_restarting", host=host, port=port)

    if getattr(sys, "frozen", False):
        os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
    else:
        # 源码态：backend 目录是工作目录（app 包所在）
        backend_dir = str(BASE_DIR)
        os.chdir(backend_dir)
        os.execv(
            sys.executable,
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", host, "--port", port],
        )
