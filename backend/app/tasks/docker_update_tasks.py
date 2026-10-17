"""Docker 在线更新的看门狗：轮询信号文件，覆盖源码后退出进程让 compose 拉起。

为什么不直接在请求里做：
覆盖 /app/backend 时，正在运行的 Python 进程仍持有旧模块；
而且 pip install 可能改动已加载的包。所以必须「覆盖 → 退出 → 重启」，由
docker compose 的 `restart: unless-stopped` 把进程重新拉起（新代码生效）。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from app.core.config import BASE_DIR
from app.core.logging import get_logger

logger = get_logger("docker_update_task")


def _updates_dir() -> Path:
    d = BASE_DIR / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def docker_update_check_once() -> bool:
    """检查并应用一次待处理的更新。返回是否触发重启。"""
    from app.services import docker_update

    signal = _updates_dir() / "apply.requested"
    if not signal.is_file():
        return False

    # 先改名，避免并发重复处理
    processing = signal.with_suffix(".processing")
    try:
        signal.rename(processing)
    except OSError:
        return False

    try:
        info = json.loads(processing.read_text(encoding="utf-8") or "{}")
    except Exception:  # noqa: BLE001
        logger.warning("docker_update_bad_signal")
        processing.unlink(missing_ok=True)
        return False

    version = str(info.get("version") or "")
    staging = Path(str(info.get("staging") or ""))
    if not version or not staging.is_dir():
        logger.warning("docker_update_staging_missing", version=version, staging=str(staging))
        processing.unlink(missing_ok=True)
        return False

    logger.info("docker_update_applying", version=version)
    result = await asyncio.to_thread(docker_update.apply_package, staging, version)

    processing.unlink(missing_ok=True)
    _updates_dir().joinpath(f"last_result_{version}.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )

    if not result.get("ok"):
        logger.error("docker_update_failed", error=result.get("error"))
        return False

    # 清理暂存（保留最近一次，便于排查）
    try:
        if staging.is_dir():
            shutil.rmtree(staging, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

    logger.warning("docker_update_restarting", version=version)
    return True


async def periodic_docker_update_check(interval_seconds: int = 10) -> None:
    """轮询更新信号；命中并成功覆盖后退出进程，让 compose 拉起新版本。"""
    while True:
        try:
            await asyncio.sleep(max(interval_seconds, 5))
            should_restart = await docker_update_check_once()
            if should_restart:
                # 给日志/文件一个落盘机会，再退出。
                # 用 os._exit 而非 SystemExit：确保 uvicorn 不会捕获后继续跑旧代码。
                await asyncio.sleep(1.0)
                os._exit(0)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("docker_update_loop_error")
