"""定时任务调度：轮询到点的任务，用独立 task 执行（不占队列 worker）。

- 执行历史：每次落一条 ScheduledTaskRun
- 失败重试：max_retries + retry_interval_seconds（抄工作流节点级退避思路）
- 并发上限：全局信号量限制同时在跑的执行数
- 通知：终态派发到通知渠道（含站内消息）
"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.services.cron import next_run as cron_next_run

logger = get_logger("scheduler")

_RUNNING: set[int] = set()
_sem: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        from app.core.config import settings

        _sem = asyncio.Semaphore(max(1, settings.scheduler_max_concurrency))
    return _sem


async def _compute_next(task) -> int | None:
    from app.services.schedule_service import compute_next

    return compute_next(task)


async def execute_task(task_id: int, *, manual: bool = False) -> None:
    """执行一个定时任务：复用 AgentRunner 或工作流引擎。落执行历史 + 终态通知。"""
    await _get_sem().acquire()
    _RUNNING.add(task_id)
    from app.core.db import AsyncSessionLocal
    from app.models import ScheduledTask, ScheduledTaskRun

    started = int(time.time() * 1000)
    run_row_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            t = await db.get(ScheduledTask, task_id)
            if not t:
                return
            run = ScheduledTaskRun(
                tenant_id=t.tenant_id, task_id=task_id, status="running",
                started_at=started, attempt=(t.retry_count or 0) + 1,
            )
            db.add(run)
            await db.commit()
            run_row_id = run.id

            ok, result_text, error_text, wf_run_id = await _do_run(db, t)
            finished = int(time.time() * 1000)
            run = await db.get(ScheduledTaskRun, run_row_id)
            run.status = "success" if ok else "failed"
            run.finished_at = finished
            run.duration_ms = finished - started
            run.output = (result_text or "")[:8000]
            run.error = (error_text or "")[:4000] or None
            run.workflow_run_id = wf_run_id

            t.last_run_at = finished
            t.last_result = (result_text or error_text or "")[:2000]
            t.run_count = (t.run_count or 0) + 1
            t.last_run_id = wf_run_id

            if ok:
                t.last_status = "success"
                t.retry_count = 0
                if t.schedule_kind == "once":
                    t.enabled = False
                    t.next_run_at = None
                else:
                    t.next_run_at = await _compute_next(t)
            else:
                t.last_status = "failed"
                # 失败重试
                if (t.retry_count or 0) < (t.max_retries or 0):
                    t.retry_count = (t.retry_count or 0) + 1
                    t.next_run_at = int(time.time() * 1000) + (t.retry_interval_seconds or 60) * 1000
                    logger.info("scheduled_task_retry", task_id=task_id, attempt=t.retry_count)
                else:
                    t.next_run_at = None if t.schedule_kind == "once" else await _compute_next(t)

            await db.commit()

        # 终态通知（独立 session，失败不影响任务状态）
        await _notify(task_id, ok=ok, result=result_text, error=error_text, manual=manual)
        # 依赖链：本任务成功后，触发以本任务为前置的下游任务（A → B）
        if ok:
            await _trigger_dependents(task_id)
    except Exception:  # noqa: BLE001
        logger.exception("scheduled_task_execute_error", task_id=task_id)
    finally:
        _RUNNING.discard(task_id)
        _get_sem().release()


async def _trigger_dependents(task_id: int) -> None:
    """本任务成功后，触发所有「以本任务为前置且启用」的下游任务。"""
    from sqlalchemy import select

    from app.core.db import AsyncSessionLocal
    from app.models import ScheduledTask

    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(ScheduledTask).where(
                    ScheduledTask.depends_on_task_id == task_id,
                    ScheduledTask.enabled.is_(True),
                )
            )).scalars().all()
            ids = [t.id for t in rows]
        for did in ids:
            if did in _RUNNING:
                continue
            logger.info("scheduled_task_dependent_triggered", upstream=task_id, downstream=did)
            asyncio.create_task(execute_task(did))
    except Exception:  # noqa: BLE001
        logger.exception("trigger_dependents_failed", task_id=task_id)



async def _do_run(db, t) -> tuple[bool, str, str, int | None]:
    """真正执行任务体。返回 (成功, 结果文本, 错误文本, workflow_run_id)。

    不创建会话、不落 Message：结果只写进 ScheduledTaskRun（在 execute_task 落库）。
    """
    from app.agents.runner import AgentRunner
    from app.agents.workflow.engine import NodeContext, execute_graph
    from app.middleware.auth_dep import get_user_permission_codes, load_principal_set
    from app.models import Agent, User, Workflow, WorkflowRun

    owner = await db.get(User, t.owner_id)
    agent = await db.get(Agent, t.agent_id)
    if not owner or not agent:
        return False, "", "目标不存在", None
    pset = await load_principal_set(db, owner)
    perms = await get_user_permission_codes(db, owner)

    try:
        if t.target_type == "workflow":
            wf = (await db.execute(
                select(Workflow).where(Workflow.agent_id == t.agent_id).order_by(Workflow.id.desc())
            )).scalars().first()
            if not wf or not wf.graph:
                raise ValueError("工作流未配置")
            inputs = t.inputs or {"query": t.prompt or t.name}
            run = WorkflowRun(
                tenant_id=t.tenant_id, workflow_id=wf.id, agent_id=t.agent_id, user_id=t.owner_id,
                conversation_id=None, status="running", input=inputs, graph_snapshot=wf.graph,
                created_at=int(time.time() * 1000),
            )
            db.add(run); await db.commit(); run_id = run.id
            ctx = NodeContext(
                db=db, ps=pset, run_id=run_id, tenant_id=t.tenant_id, inputs=inputs,
                default_model_config_id=agent.model_config_id, default_kb_ids=agent.kb_ids,
                default_system=agent.system_prompt, default_temperature=(agent.config or {}).get("temperature"),
                perms=perms,
            )
            final, _ = await execute_graph(wf.graph, inputs, ctx)
            r2 = await db.get(WorkflowRun, run_id)
            r2.status = "success"; r2.output = final; r2.finished_at = int(time.time() * 1000)
            text = str(final.get("output", final)) if isinstance(final, dict) else str(final)
            return True, text, "", run_id
        else:
            # 不建会话、不落 Message：无人值守地跑一次提示词
            runner = AgentRunner(
                db, agent=agent, ps=pset, conversation=None, history=[], perms=perms,
                summary=None, persist=False,
            )
            text = ""
            async for evt in runner.run(t.prompt or t.name):
                if evt.get("type") == "delta":
                    text += evt.get("text", "")
            return True, text, "", None
    except Exception as e:  # noqa: BLE001
        logger.exception("scheduled_task_run_failed", task_id=t.id)
        return False, "", str(e)[:1000], None


async def _notify(task_id: int, *, ok: bool, result: str, error: str, manual: bool = False) -> None:
    """终态通知：按任务通知开关（notify_on）决定是否发，附结果摘要。"""
    from app.core.db import AsyncSessionLocal
    from app.models import ScheduledTask, ScheduledTaskRun
    from app.notifiers.base import NotificationMessage
    from app.notifiers.registry import dispatch

    try:
        async with AsyncSessionLocal() as db:
            t = await db.get(ScheduledTask, task_id)
            if not t:
                return
            mode = t.notify_on or "fail"
            if mode == "never":
                return
            if mode == "success" and not ok:
                return
            if mode == "fail" and ok:
                return
            prefix = "手动运行" if manual else "定时任务"
            # 取最近一条执行记录补充耗时/结果摘要
            last_run = (await db.execute(
                select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id)
                .order_by(ScheduledTaskRun.id.desc()).limit(1)
            )).scalars().first()
            summary = (result[:400] if ok else error[:400]) or ""
            msg = NotificationMessage(
                title=f"{prefix}「{t.name}」{'执行成功' if ok else '执行失败'}",
                body=summary,
                level="success" if ok else "error",
                kind="task", link="/scheduled", ref_type="scheduled_task", ref_id=task_id,
                user_id=t.owner_id,
                meta={
                    "task_id": task_id, "task_name": t.name,
                    "status": "success" if ok else "failed",
                    "duration_ms": last_run.duration_ms if last_run else None,
                    "run_id": last_run.id if last_run else None,
                },
            )
            await dispatch(db, tenant_id=t.tenant_id, msg=msg, user_id=t.owner_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("scheduled_task_notify_error", task_id=task_id)


async def scheduler_loop(interval_seconds: int = 30) -> None:
    """后台轮询：到点任务 CAS 抢占后独立执行。"""
    from app.core.db import AsyncSessionLocal
    from app.models import ScheduledTask

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with AsyncSessionLocal() as db:
                now = int(time.time() * 1000)
                rows = (await db.execute(
                    select(ScheduledTask).where(
                        ScheduledTask.enabled.is_(True),
                        ScheduledTask.trigger_kind == "schedule",
                        ScheduledTask.next_run_at.is_not(None),
                        ScheduledTask.next_run_at <= now,
                    )
                )).scalars().all()
                for t in rows:
                    if t.id in _RUNNING:
                        continue
                    # once 任务派发后清空 next_run_at，避免每轮重复触发
                    nxt = None if t.schedule_kind == "once" else await _compute_next(t)
                    # CAS 抢占：只有把 next_run_at 从旧值改成功才派发
                    res = await db.execute(
                        update(ScheduledTask)
                        .where(ScheduledTask.id == t.id, ScheduledTask.next_run_at == t.next_run_at)
                        .values(next_run_at=nxt, last_status="running")
                    )
                    if res.rowcount == 1:
                        await db.commit()
                        asyncio.create_task(execute_task(t.id))
                await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler_loop_error")
