"""系统运维接口：数据库切换向导、备份/还原、初始化、重置密码、清理。

把原本需命令行/改文件的操作搬进 Web。全部需 system:manage 权限。
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR, DATA_DIR, settings
from app.core.db import get_db, make_engine
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import User
from app.services.audit_service import audited

router = APIRouter(prefix="/system", tags=["system_ops"])

_START_TS = time.time()
PENDING_DB_FILE = DATA_DIR / "pending_db.txt"

# 允许一键安装的目标 → 固定包名白名单（绝不接受用户自定义包名）
DRIVER_PACKAGES: dict[str, list[str]] = {
    "postgres": ["asyncpg", "pgvector"],
    "mysql": ["asyncmy"],
    "redis": ["redis"],
}
# 各库所需驱动（import 名）
_DB_DRIVERS = {
    "sqlite": ["aiosqlite"],
    "postgres": ["asyncpg"],
    "mysql": ["asyncmy"],
}


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _mask_db_url(url: str) -> str:
    """连接串脱敏（隐藏密码）。"""
    import re

    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", url or "")


def _db_kind(url: str) -> str:
    if url.startswith("sqlite"):
        return "sqlite"
    if "postgres" in url:
        return "postgres"
    if "mysql" in url:
        return "mysql"
    return "unknown"


def _sqlite_path(url: str) -> Path | None:
    """从 sqlite URL 解析出文件路径（相对路径按 BASE_DIR 解析）。"""
    if not url.startswith("sqlite"):
        return None
    raw = url.split("///", 1)[-1]
    p = Path(raw)
    if not p.is_absolute():
        p = (BASE_DIR / raw).resolve()
    return p


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size if p.exists() else 0
    except OSError:
        return 0


def _dir_size(p: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


class DbUrlIn(BaseModel):
    database_url: str


class InstallDriverIn(BaseModel):
    target: str  # postgres | mysql | redis


class ResetPwIn(BaseModel):
    username: str = "admin"
    new_password: str


class CleanupIn(BaseModel):
    scope: str = "all"  # temp | orphan_artifacts | all


# ==================== 系统信息 ====================
@router.get("/info")
async def system_info(
    user: User = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    url = settings.database_url
    kind = _db_kind(url)
    sp = _sqlite_path(url)
    tables = 0
    try:
        from sqlalchemy import inspect as _inspect

        def _count(sync_session):
            bind = sync_session.get_bind()
            return len(_inspect(bind).get_table_names())

        tables = await db.run_sync(_count)
    except Exception:  # noqa: BLE001
        pass

    return {
        "db_kind": kind,
        "db_url_masked": _mask_db_url(url),
        "db_file": str(sp) if sp else None,
        "db_file_size": _file_size(sp) if sp else 0,
        "driver_required": _DB_DRIVERS.get(kind, []),
        "driver_ok": all(_has_module(m) for m in _DB_DRIVERS.get(kind, [])),
        "vector_backend": settings.resolved_vector_backend,
        "task_backend": settings.task_backend,
        "data_dir": str(DATA_DIR),
        "data_dir_size": _dir_size(DATA_DIR),
        "files_dir_size": _dir_size(Path(settings.storage_local_dir)),
        "uptime_seconds": int(time.time() - _START_TS),
        "table_count": tables,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }


# ==================== 切库向导 ====================
@router.get("/db/drivers")
async def db_drivers(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """各可选库所需驱动是否已装。"""
    return {
        "sqlite": {"packages": _DB_DRIVERS["sqlite"],
                   "ok": all(_has_module(m) for m in _DB_DRIVERS["sqlite"])},
        "postgres": {"packages": DRIVER_PACKAGES["postgres"],
                     "ok": all(_has_module(m) for m in ("asyncpg", "pgvector"))},
        "mysql": {"packages": _DB_DRIVERS["mysql"],
                  "ok": all(_has_module(m) for m in _DB_DRIVERS["mysql"])},
        "redis": {"packages": DRIVER_PACKAGES["redis"], "ok": _has_module("redis")},
    }


@router.post("/db/test")
async def db_test(
    body: DbUrlIn,
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """用一次性临时 engine 探活目标库（不碰主 engine）。"""
    url = (body.database_url or "").strip()
    if not url:
        raise ValidationError("请填写连接串")
    kind = _db_kind(url)
    missing = [m for m in _DB_DRIVERS.get(kind, []) if not _has_module(m)]
    if missing:
        return {"ok": False, "kind": kind,
                "message": f"缺少驱动：{', '.join(missing)}。请先在下方「一键安装驱动」。",
                "driver_missing": missing}
    eng = None
    try:
        eng = make_engine(url)
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ok": True, "kind": kind, "message": "连接成功"}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        low = msg.lower()
        if "refused" in low or "could not connect" in low or "connection" in low:
            hint = "无法连接（服务未启动/地址端口不对/防火墙）"
        elif "password" in low or "authentication" in low or "认证" in msg:
            hint = "认证失败（用户名或密码错误）"
        elif "does not exist" in low or "unknown database" in low or "库不存在" in msg:
            hint = "数据库不存在（请先在数据库里创建该库）"
        else:
            hint = "连接失败"
        return {"ok": False, "kind": kind, "message": f"{hint}：{msg[:200]}"}
    finally:
        if eng is not None:
            try:
                await eng.dispose()
            except Exception:  # noqa: BLE001
                pass


@router.post("/db/install-driver")
async def db_install_driver(
    body: InstallDriverIn,
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """一键安装某类库的驱动（白名单包名，子进程 pip）。"""
    target = body.target
    pkgs = DRIVER_PACKAGES.get(target)
    if not pkgs:
        raise ValidationError(f"不支持的目标：{target}（可选 postgres/mysql/redis）")
    import asyncio

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", *pkgs,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        log = (out or b"").decode("utf-8", errors="ignore")
        ok = proc.returncode == 0
    except asyncio.TimeoutError:
        return {"ok": False, "message": "安装超时（>3 分钟）", "log": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"安装失败：{str(e)[:200]}", "log": ""}
    # importlib 缓存需失效才能看到新装的包
    importlib.invalidate_caches()
    return {"ok": ok, "message": "安装完成" if ok else "安装失败", "log": log[-4000:],
            "packages": pkgs}


@router.post("/db/init")
async def db_init(
    body: DbUrlIn,
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """对目标库建表（create_all + 补列）。用于切换前初始化空库。"""
    url = (body.database_url or "").strip()
    if not url:
        raise ValidationError("请填写连接串")
    from app.core.db import init_models_for

    eng = None
    try:
        eng = make_engine(url)
        tables = await init_models_for(eng)
        return {"ok": True, "message": f"已建 {len(tables)} 张表", "table_count": len(tables)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"建表失败：{str(e)[:200]}"}
    finally:
        if eng is not None:
            try:
                await eng.dispose()
            except Exception:  # noqa: BLE001
                pass


@router.post("/db/save-restart")
@audited("system.db_switch", "system")
async def db_save_restart(
    body: DbUrlIn,
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """保存目标库并重启。写入 pending_db.txt，重启后验证通过才提升为生效值；失败自动回退。"""
    url = (body.database_url or "").strip()
    if not url:
        raise ValidationError("请填写连接串")
    prev = settings.database_url
    if url == prev:
        return {"ok": False, "message": "与当前连接串相同，无需切换"}
    try:
        PENDING_DB_FILE.write_text(
            json.dumps({"target_url": url, "previous_url": prev,
                        "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        raise ValidationError(f"无法写入切换标记：{e}") from e
    # 延迟重启（响应后再触发）
    import asyncio

    from app.api.v1.settings import _restart_process

    async def _do() -> None:
        await asyncio.sleep(0.8)
        _restart_process()

    asyncio.get_running_loop().create_task(_do())
    return {"ok": True, "message": "正在切换数据库并重启；若目标库不可用会自动回退"}


@router.post("/db/migrate")
@audited("system.db_migrate", "system")
async def db_migrate(
    user: User = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """对当前主库重跑建表+补列（等价重启时的自动补列）。"""
    from app.core.db import async_engine, init_models_for

    tables = await init_models_for(async_engine)
    return {"ok": True, "message": f"已同步表结构（{len(tables)} 张表）"}


# ==================== 备份 / 还原 ====================
@router.get("/db/backup")
async def db_backup(
    user: User = Depends(require_permission("system:manage")),
):
    """下载当前 SQLite 库文件。"""
    url = settings.database_url
    if _db_kind(url) != "sqlite":
        raise ValidationError("当前不是 SQLite，无法直接下载库文件；请改用数据导出。")
    p = _sqlite_path(url)
    if not p or not p.exists():
        raise NotFoundError("数据库文件不存在")
    # 触发 WAL 落盘，导出前先 checkpoint 到主库文件
    try:
        eng = make_engine(url)
        async with eng.connect() as conn:
            await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        await eng.dispose()
    except Exception:  # noqa: BLE001
        pass
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return FileResponse(str(p), filename=f"rag_backup_{ts}.db",
                        media_type="application/octet-stream")


@router.post("/db/restore")
@audited("system.db_restore", "system")
async def db_restore(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """上传 .db 还原（覆盖前自动备份旧库；需重启生效）。"""
    url = settings.database_url
    if _db_kind(url) != "sqlite":
        raise ValidationError("当前不是 SQLite，不支持直接还原库文件。")
    p = _sqlite_path(url)
    if not p:
        raise NotFoundError("无法定位数据库文件")
    data = await file.read()
    if data[:16] != b"SQLite format 3\x00":
        raise ValidationError("上传的文件不是合法的 SQLite 数据库")
    # 备份旧库
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if p.exists():
        shutil.copy2(p, p.with_name(f"{p.name}.bak.{ts}"))
    # 覆盖（连同 WAL/SHM 清理）
    p.write_bytes(data)
    for sfx in ("-wal", "-shm"):
        try:
            Path(str(p) + sfx).unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True, "message": "已还原（旧库已自动备份），请重启服务以完全生效。"}


@router.post("/db/reset")
@audited("system.db_reset", "system")
async def db_reset(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """把连接串回退到默认 SQLite（崩溃兜底用）。"""
    default = f"sqlite+aiosqlite:///{(DATA_DIR / 'rag.db').as_posix()}"
    try:
        PENDING_DB_FILE.write_text(
            json.dumps({"target_url": default, "previous_url": settings.database_url,
                        "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        raise ValidationError(f"无法写入：{e}") from e
    import asyncio

    from app.api.v1.settings import _restart_process

    async def _do() -> None:
        await asyncio.sleep(0.8)
        _restart_process()

    asyncio.get_running_loop().create_task(_do())
    return {"ok": True, "message": "正在回退到默认 SQLite 并重启"}


# ==================== 初始化 / 重置 ====================
@router.post("/seed")
@audited("system.seed", "system")
async def system_seed(
    user: User = Depends(require_permission("system:manage")),
) -> dict:
    """初始化默认租户/管理员/角色（幂等）。"""
    from app.bootstrap import seed_all

    await seed_all()
    return {"ok": True, "message": "已初始化（已存在的会跳过）"}


@router.post("/reset-admin-password")
@audited("system.reset_admin_pw", "user")
async def reset_admin_password(
    body: ResetPwIn,
    user: User = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重置某个账号的密码。"""
    from sqlalchemy import select

    from app.core.security import hash_password

    if len(body.new_password or "") < 6:
        raise ValidationError("密码至少 6 位")
    target = (await db.execute(
        select(User).where(User.tenant_id == user.tenant_id, User.username == body.username)
    )).scalar_one_or_none()
    if not target:
        raise NotFoundError(f"账号不存在：{body.username}")
    target.password_hash = hash_password(body.new_password)
    await db.flush()
    return {"ok": True, "message": f"已重置「{body.username}」的密码"}


# ==================== 清理 ====================
@router.post("/cleanup")
@audited("system.cleanup", "system")
async def system_cleanup(
    body: CleanupIn,
    user: User = Depends(require_permission("system:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """清理临时文件 / 孤儿产物。"""
    from sqlalchemy import select

    from app.models import Artifact

    removed = 0
    freed = 0
    if body.scope in ("temp", "all"):
        # 保护：绝不删当前生效的数据库文件及其 WAL/SHM
        cur = _sqlite_path(settings.database_url)
        protected: set[str] = set()
        if cur:
            protected = {cur.name, cur.name + "-wal", cur.name + "-shm"}
        # 仅清理明确的散落临时文件（不用 test_* 通配，避免误删用户库）
        temp_names = {"a.json", "bob_id.txt", "run.json", "wf.json", "dtest.log",
                      "desktop_final.log", "desktop_run.log", "electron.log"}
        for f in DATA_DIR.glob("*"):
            if not f.is_file() or f.name in protected:
                continue
            if f.name in temp_names or f.suffix == ".tmp":
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    removed += 1; freed += sz
                except OSError:
                    pass
    if body.scope in ("orphan_artifacts", "all"):
        # data/files 下无 Artifact 记录的孤儿文件
        files_dir = Path(settings.storage_local_dir)
        if files_dir.exists():
            keys = {a.file_key for a in (await db.execute(select(Artifact))).scalars().all()}
            for f in files_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(files_dir).as_posix()
                    if rel not in keys and rel.replace("\\", "/") not in keys:
                        try:
                            sz = f.stat().st_size
                            f.unlink()
                            removed += 1; freed += sz
                        except OSError:
                            pass
    return {"ok": True, "removed": removed, "freed_bytes": freed,
            "message": f"已清理 {removed} 个文件，释放 {freed} 字节"}
