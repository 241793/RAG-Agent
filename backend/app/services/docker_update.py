"""Docker 部署的在线更新：用下载的 docker 包覆盖容器内 /app 下的源码与前端。

与桌面版的差异
--------------
- 桌面版换的是**安装目录里的 exe**，由外部 bat 脚本在进程退出后执行；
- Docker 版换的是**挂载目录里的源码**（/app → 宿主机 ./rag-web），
  覆盖完直接退出进程，靠 compose 的 `restart: unless-stopped` 拉起。

目录约定（与 config.py / Dockerfile 保持一致）
--------------------------------------------
BASE_DIR      = /app/backend        ← 源码
RESOURCE_DIR  = /app                ← web/dist 与 CHANGELOG.md 所在
所以覆盖目标：/app/backend ← 包内 backend/，/app/web/dist ← 包内 web/dist。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.config import BASE_DIR, RESOURCE_DIR
from app.core.logging import get_logger

logger = get_logger("docker_update")

# 需要备份/替换的相对路径（相对 RESOURCE_DIR）
PROTECTED_DIRS = ("backend", "web/dist")


def _app_root() -> Path:
    """容器内工作根目录（= 宿主机挂载的 ./rag-web）。"""
    return RESOURCE_DIR


def _backup_root() -> Path:
    from app.core.config import BASE_DIR as bd

    d = bd / "updates" / "backup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_tree(src: Path, dst: Path) -> None:
    """把 src 目录内容复制进 dst（dst 保留其它文件，只覆盖同名）。"""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def backup_current(version: str) -> Path:
    """把当前 backend/ 与 web/dist 备份到 updates/backup/<version>-<ts>。"""
    import time

    root = _app_root()
    base = _backup_root() / f"{version}-{int(time.time())}"
    dest = base
    # 同一秒内重复备份（如失败重试）会撞名 → 加后缀，绝不覆盖已有备份
    n = 1
    while dest.exists():
        dest = base.with_name(f"{base.name}-{n}")
        n += 1
    dest.mkdir(parents=True, exist_ok=True)
    for rel in PROTECTED_DIRS:
        src = root / rel
        if src.exists():
            tgt = dest / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            # dst 已由上面 mkdir 创建，故 dirs_exist_ok=True
            shutil.copytree(src, tgt, dirs_exist_ok=True)
    logger.info("docker_update_backup", path=str(dest))
    return dest


def restore_backup(backup_dir: Path) -> None:
    """从备份还原（失败时回滚）。"""
    root = _app_root()
    for rel in PROTECTED_DIRS:
        src = backup_dir / rel
        if src.exists():
            _copy_tree(src, root / rel)
    logger.warning("docker_update_restored", path=str(backup_dir))


def apply_package(staging: Path, version: str) -> dict:
    """把解压好的包覆盖到 /app。返回 {"ok", "error"?}。不处理重启。"""
    root = _app_root()
    src_backend = staging / "backend"
    src_webdist = staging / "web" / "dist"

    if not (src_backend / "app" / "main.py").is_file():
        return {"ok": False, "error": "更新包结构异常：缺少 backend/app/main.py"}
    if not (src_webdist / "index.html").is_file():
        return {"ok": False, "error": "更新包结构异常：缺少 web/dist/index.html"}

    backup = None
    try:
        backup = backup_current(version)

        logger.info("docker_update_copy", version=version)
        _copy_tree(src_backend, root / "backend")
        _copy_tree(src_webdist, root / "web" / "dist")

        # 更新日志（供 changelog_service 读）
        cl = staging / "CHANGELOG.md"
        if cl.is_file():
            shutil.copy2(cl, root / "CHANGELOG.md")

        # 依赖可能有变化：装一次（无变化时 pip 很快跳过）
        req = root / "backend" / "requirements.txt"
        pip_msg = ""
        if req.is_file():
            try:
                proc = subprocess.run(
                    ["python", "-m", "pip", "install", "--no-cache-dir", "-r", str(req)],
                    capture_output=True, text=True, timeout=600,
                )
                if proc.returncode != 0:
                    pip_msg = (proc.stderr or proc.stdout or "")[-400:]
                    logger.error("docker_update_pip_failed", rc=proc.returncode, msg=pip_msg)
                    restore_backup(backup)
                    return {"ok": False, "error": f"依赖安装失败，已回滚：{pip_msg[:200]}"}
            except Exception as e:  # noqa: BLE001
                logger.exception("docker_update_pip_exception")
                restore_backup(backup)
                return {"ok": False, "error": f"依赖安装异常，已回滚：{str(e)[:200]}"}

        logger.info("docker_update_applied", version=version)
        return {"ok": True, "backup": str(backup)}
    except Exception as e:  # noqa: BLE001
        logger.exception("docker_update_apply_failed")
        if backup:
            restore_backup(backup)
        return {"ok": False, "error": f"覆盖失败，已回滚：{str(e)[:200]}"}
