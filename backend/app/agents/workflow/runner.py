"""工作流流式执行器：边执行边产出事件（与 SSE 连接解耦，客户端断开仍跑完）。

被 chat 侧（agents.py）与编排页运行（workflow.py）共用，消除两份重复逻辑。
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflow.engine import NodeContext, WorkflowPaused, execute_graph
from app.core.logging import get_logger
from app.services.permission import PrincipalSet

logger = get_logger("workflow")

# 持有后台任务引用，避免被 GC
_BG_TASKS: set = set()
_DONE = "__wf_done__"


def _vars_from_records(records: list[dict]) -> dict:
    """从节点记录重建 resume 变量（node_id → output），仅取执行成功且有输出的节点。"""
    import json

    out: dict = {}
    for r in records:
        if r.get("status") != "success":
            continue
        val = r.get("output")
        try:
            json.dumps(val)
            out[r["node_id"]] = val
        except (TypeError, ValueError):
            out[r["node_id"]] = str(val)[:5000]
    return out


async def stream_workflow(
    *,
    graph: dict,
    inputs: dict,
    run_id: int,
    tenant_id: int,
    ps: PrincipalSet,
    default_model_config_id: int | None = None,
    default_kb_ids: list[int] | None = None,
    default_system: str | None = None,
    default_temperature: float | None = None,
    approval: dict | None = None,
    resume: dict | None = None,
    perms: set[str] | None = None,
    on_terminal: Callable[[AsyncSession, dict], Awaitable[None]] | None = None,
) -> AsyncIterator[dict]:
    """执行工作流并逐事件 yield（node_started/node_finished/run_finished）。

    - 独立 session + 后台 task：客户端断开不中断、终态必落库。
    - on_terminal(db, info)：落库后回调（chat 侧用它写 assistant Message）。
    - approval：审批决策 {node_id: "approve"|"reject"}；resume：{variables}。
    """
    from app.core.db import AsyncSessionLocal
    from app.models import NodeRun, WorkflowRun

    queue: asyncio.Queue = asyncio.Queue()

    async def _run():
        async with AsyncSessionLocal() as wdb:
            async def emit(evt: dict):
                await queue.put(evt)

            ctx = NodeContext(
                db=wdb, ps=ps, run_id=run_id, tenant_id=tenant_id, inputs=inputs, emit=emit,
                default_model_config_id=default_model_config_id, default_kb_ids=default_kb_ids,
                default_system=default_system, default_temperature=default_temperature,
                approval=approval, perms=perms,
            )
            t0 = time.time()
            err_msg = None
            final_out: dict = {}
            records: list[dict] = []
            paused: WorkflowPaused | None = None
            try:
                final_out, records = await execute_graph(graph, inputs, ctx, resume=resume)
            except WorkflowPaused as p:
                paused = p
            except Exception as e:  # noqa: BLE001
                err_msg = str(e)[:300]
            latency_ms = int((time.time() - t0) * 1000)

            # 审批暂停：置 waiting，存变量快照，SSE 发 approval_required
            if paused is not None:
                try:
                    r2 = await wdb.get(WorkflowRun, run_id)
                    r2.status = "waiting"
                    r2.pending_node_id = paused.node_id
                    r2.state = {"variables": paused.variables or _vars_from_records(records)}
                    r2.finished_at = int(time.time() * 1000)
                    for rr in paused.records:
                        wdb.add(NodeRun(
                            tenant_id=tenant_id, run_id=run_id, node_id=rr["node_id"],
                            node_type=rr["node_type"], seq=rr["seq"], status=rr["status"],
                            input=rr.get("input"), output=rr.get("output"), error_msg=rr.get("error_msg"),
                            retry_count=rr.get("retry_count", 0), latency_ms=rr.get("latency_ms", 0),
                            created_at=int(time.time() * 1000),
                        ))
                    await wdb.commit()
                except Exception:  # noqa: BLE001
                    await wdb.rollback()
                await queue.put({"type": "approval_required", "node_id": paused.node_id, "run_id": run_id, **paused.info})
                await queue.put({"type": _DONE, "paused": True, "run_id": run_id,
                                 "status": "waiting", "node_id": paused.node_id})
                return

            out_text = str(final_out.get("output", final_out)) if isinstance(final_out, dict) else str(final_out)
            if err_msg:
                out_text = f"[工作流执行失败] {err_msg}"
            try:
                r2 = await wdb.get(WorkflowRun, run_id)
                if err_msg:
                    r2.status = "failed"; r2.error_msg = err_msg
                else:
                    r2.status = "success"; r2.output = final_out
                r2.latency_ms = latency_ms
                r2.finished_at = int(time.time() * 1000)
                for rr in records:
                    wdb.add(NodeRun(
                        tenant_id=tenant_id, run_id=run_id, node_id=rr["node_id"],
                        node_type=rr["node_type"], seq=rr["seq"], status=rr["status"],
                        input=rr.get("input"), output=rr.get("output"), error_msg=rr.get("error_msg"),
                        retry_count=rr.get("retry_count", 0), latency_ms=rr.get("latency_ms", 0),
                        created_at=int(time.time() * 1000),
                    ))
                if on_terminal:
                    await on_terminal(wdb, {"text": out_text, "err": err_msg, "run_id": run_id, "final": final_out})
                await wdb.commit()
            except Exception:  # noqa: BLE001
                await wdb.rollback()
                logger.exception("workflow_finalize_failed", run_id=run_id)
            # 事件触发：工作流运行完成（供定时任务/其他流程消费）
            try:
                from app.tasks.event_bus import publish

                wf_id = None
                r3 = await wdb.get(WorkflowRun, run_id)
                if r3:
                    wf_id = r3.workflow_id
                await publish(
                    "workflow.completed" if not err_msg else "workflow.failed",
                    tenant_id=tenant_id,
                    payload={"run_id": run_id, "workflow_id": wf_id, "status": "failed" if err_msg else "success"},
                )
            except Exception:  # noqa: BLE001
                logger.exception("workflow_event_publish_failed", run_id=run_id)
            await queue.put({
                "type": _DONE, "err": err_msg, "text": out_text, "run_id": run_id,
                "status": "failed" if err_msg else "success", "output": final_out,
            })

    bg = asyncio.create_task(_run())
    _BG_TASKS.add(bg)
    bg.add_done_callback(_BG_TASKS.discard)

    while True:
        evt = await queue.get()
        etype = evt.get("type") if isinstance(evt, dict) else "node"
        if etype == _DONE:
            yield evt
            break
        yield evt
