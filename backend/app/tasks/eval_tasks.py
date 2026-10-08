"""RAG 评测后台任务：独立 session 跑一次评测。"""
from __future__ import annotations

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.tasks.queue import submit

logger = get_logger("eval_task")


async def run_eval_job(run_id: int, top_k: int = 5) -> None:
    """执行一次评测（独立 session）。"""
    from app.services.eval_service import run_eval

    async with AsyncSessionLocal() as db:
        try:
            await run_eval(db, run_id=run_id, top_k=top_k)
        except Exception:  # noqa: BLE001
            logger.exception("eval_job_failed", run_id=run_id)
            from app.models import EvalRun

            r = await db.get(EvalRun, run_id)
            if r:
                r.status = "failed"
                r.error = "评测执行异常"
                await db.commit()


async def enqueue_eval(run_id: int, top_k: int = 5) -> None:
    await submit(f"eval:{run_id}", lambda: run_eval_job(run_id, top_k))
