"""进程内异步任务队列（零依赖，默认）。

抽象为 submit(task_callable) 接口，后续可换成 Celery（settings.task_backend=celery）。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger("tasks")

_queue: "asyncio.Queue[tuple[str, Callable[[], Awaitable[None]]]] | None" = None
_workers: list[asyncio.Task] = []
_started = False


def _ensure_queue() -> "asyncio.Queue":
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


async def _worker(name: str) -> None:
    q = _ensure_queue()
    while True:
        task_name, fn = await q.get()
        try:
            logger.info("task_start", task=task_name)
            await fn()
            logger.info("task_done", task=task_name)
        except Exception:  # noqa: BLE001
            logger.exception("task_failed", task=task_name)
        finally:
            q.task_done()


async def start_workers(n: int = 2) -> None:
    global _started
    if _started:
        return
    for i in range(n):
        _workers.append(asyncio.create_task(_worker(f"worker-{i}")))
    _started = True
    logger.info("workers_started", count=n)


async def stop_workers() -> None:
    global _started
    for w in _workers:
        w.cancel()
    _workers.clear()
    _started = False


async def submit(name: str, fn: Callable[[], Awaitable[None]]) -> None:
    q = _ensure_queue()
    await q.put((name, fn))
