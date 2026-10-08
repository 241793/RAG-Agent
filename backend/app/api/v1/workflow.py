"""工作流接口：graph 存取、发布、SSE 运行、运行轨迹。"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, get_db
from app.core.errors import ConflictError, NotFoundError
from app.middleware.auth_dep import load_principal_set, require_permission
from app.services.audit_service import audited, record_audit
from app.models import Agent, NodeRun, User, Workflow, WorkflowRun
from app.services.permission import PrincipalSet

router = APIRouter(tags=["workflow"])


class GraphIn(BaseModel):
    graph: dict
    name: str | None = None


class RunIn(BaseModel):
    inputs: dict = {}


async def _get_agent_workflow(db: AsyncSession, agent_id: int, tenant_id: int) -> tuple[Agent, Workflow]:
    a = await db.get(Agent, agent_id)
    if not a or a.tenant_id != tenant_id:
        raise NotFoundError("智能体不存在")
    wf = (
        await db.execute(select(Workflow).where(Workflow.agent_id == agent_id).order_by(Workflow.id.desc()))
    ).scalars().first()
    if not wf:
        wf = Workflow(tenant_id=tenant_id, agent_id=agent_id, name=a.name, graph={"nodes": [], "edges": []})
        db.add(wf)
        await db.flush()
    return a, wf


@router.get("/approvals/pending")
async def pending_approvals(
    user: User = Depends(require_permission("workflow:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """待我审批的工作流运行（status=waiting）。"""
    rows = (
        await db.execute(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == user.tenant_id, WorkflowRun.status == "waiting"
            ).order_by(WorkflowRun.id.desc()).limit(100)
        )
    ).scalars().all()
    # 补智能体名
    agent_ids = [r.agent_id for r in rows if r.agent_id]
    names: dict[int, str] = {}
    if agent_ids:
        for a in (await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))).scalars().all():
            names[a.id] = a.name
    return [
        {"run_id": r.id, "agent_id": r.agent_id, "agent_name": names.get(r.agent_id or 0, f"#{r.agent_id}"),
         "pending_node_id": r.pending_node_id, "input": r.input, "created_at": r.created_at}
        for r in rows
    ]


@router.get("/agents/{agent_id}/workflow")
async def get_workflow(
    agent_id: int,
    user: User = Depends(require_permission("workflow:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, wf = await _get_agent_workflow(db, agent_id, user.tenant_id)
    return {"id": wf.id, "graph": wf.graph or {"nodes": [], "edges": []}, "version": wf.version, "status": wf.status}


@router.put("/agents/{agent_id}/workflow")
@audited("workflow.save", "workflow", id_arg="agent_id")
async def save_workflow(
    agent_id: int,
    body: GraphIn,
    user: User = Depends(require_permission("workflow:edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.agents.workflow.engine import validate_graph

    _, wf = await _get_agent_workflow(db, agent_id, user.tenant_id)
    # 允许保存空图（编辑中）；非空则校验
    if body.graph.get("nodes"):
        validate_graph(body.graph)
    wf.graph = body.graph
    if body.name:
        wf.name = body.name
    await db.flush()
    return {"message": "已保存", "version": wf.version}


@router.post("/agents/{agent_id}/workflow/publish")
@audited("workflow.publish", "workflow", id_arg="agent_id")
async def publish_workflow(
    agent_id: int,
    user: User = Depends(require_permission("workflow:edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.agents.workflow.engine import validate_graph
    from app.models.base import utcnow

    _, wf = await _get_agent_workflow(db, agent_id, user.tenant_id)
    validate_graph(wf.graph or {})
    wf.status = "published"
    wf.version = (wf.version or 1) + 1
    wf.published_at = utcnow()
    await db.flush()
    return {"message": "已发布", "version": wf.version}


@router.post("/agents/{agent_id}/workflow/run")
async def run_workflow(
    agent_id: int,
    body: RunIn,
    user: User = Depends(require_permission("workflow:run")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    from app.agents.workflow.runner import stream_workflow

    a = await db.get(Agent, agent_id)
    if not a or a.tenant_id != user.tenant_id:
        raise NotFoundError("智能体不存在")
    wf = (
        await db.execute(select(Workflow).where(Workflow.agent_id == agent_id).order_by(Workflow.id.desc()))
    ).scalars().first()
    if not wf or not wf.graph:
        raise NotFoundError("工作流未配置")

    run = WorkflowRun(
        tenant_id=user.tenant_id, workflow_id=wf.id, agent_id=agent_id, user_id=user.id,
        status="running", input=body.inputs, graph_snapshot=wf.graph, created_at=int(time.time() * 1000),
    )
    db.add(run)
    await db.commit()
    run_id = run.id
    graph = wf.graph
    inputs = body.inputs

    async def gen():
        pset = await load_principal_set(db, user)
        async for evt in stream_workflow(
            graph=graph, inputs=inputs, run_id=run_id, tenant_id=user.tenant_id, ps=pset,
            default_model_config_id=a.model_config_id, default_kb_ids=a.kb_ids,
            default_system=a.system_prompt, default_temperature=(a.config or {}).get("temperature"),
        ):
            etype = evt.get("type", "node")
            yield f"event: {etype}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agents/{agent_id}/workflow/runs")
async def list_runs(
    agent_id: int,
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(require_permission("workflow:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出该工作流的历次运行。"""
    a = await db.get(Agent, agent_id)
    if not a or a.tenant_id != user.tenant_id:
        raise NotFoundError("智能体不存在")
    rows = (
        await db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.agent_id == agent_id, WorkflowRun.tenant_id == user.tenant_id)
            .order_by(WorkflowRun.id.desc())
            .limit(min(limit, 100)).offset(offset)
        )
    ).scalars().all()
    return {"runs": [
        {"id": r.id, "status": r.status, "latency_ms": r.latency_ms,
         "created_at": r.created_at, "finished_at": r.finished_at,
         "error_msg": r.error_msg, "input": r.input}
        for r in rows
    ]}


@router.get("/workflow-runs/{run_id}")
async def get_run(
    run_id: int,
    user: User = Depends(require_permission("workflow:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await db.get(WorkflowRun, run_id)
    if not run or run.tenant_id != user.tenant_id:
        raise NotFoundError("运行记录不存在")
    nodes = (
        await db.execute(select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.seq))
    ).scalars().all()
    return {
        "run": {
            "id": run.id, "status": run.status, "input": run.input, "output": run.output,
            "error_msg": run.error_msg, "latency_ms": run.latency_ms,
            "pending_node_id": run.pending_node_id,
        },
        "nodes": [
            {"node_id": n.node_id, "node_type": n.node_type, "seq": n.seq, "status": n.status,
             "input": n.input, "output": n.output, "error_msg": n.error_msg}
            for n in nodes
        ],
    }


class ApproveIn(BaseModel):
    decision: str  # approve | reject
    comment: str | None = None


@router.post("/workflow-runs/{run_id}/approve")
async def approve_run(
    run_id: int,
    body: ApproveIn,
    user: User = Depends(require_permission("workflow:run")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """人工审批：通过则从快照恢复执行（复用缓存，不重跑上游），拒绝则终止。"""
    from sqlalchemy import update as _upd

    from app.agents.workflow.runner import stream_workflow

    run = await db.get(WorkflowRun, run_id)
    if not run or run.tenant_id != user.tenant_id:
        raise NotFoundError("运行记录不存在")
    if run.status != "waiting":
        raise ConflictError("该运行不在等待审批状态")
    decision = body.decision if body.decision in ("approve", "reject") else "reject"
    pending = run.pending_node_id

    # CAS 防重复审批
    res = await db.execute(
        _upd(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.status == "waiting")
        .values(status="running" if decision == "approve" else "canceled")
    )
    if res.rowcount != 1:
        await db.rollback()
        raise ConflictError("该运行已被处理")
    await db.commit()
    record_audit(db, action="workflow.approve", resource_type="workflow_run",
                 resource_id=run_id, after={"decision": decision})
    await db.commit()

    if decision == "reject":
        async def rej():
            yield f"event: run_finished\ndata: {json.dumps({'status': 'canceled', 'run_id': run_id}, ensure_ascii=False)}\n\n"
        return StreamingResponse(rej(), media_type="text/event-stream")

    graph = run.graph_snapshot or {}
    inputs = run.input or {}
    resume = run.state or {}
    approval = {pending: "approve"} if pending else {}
    agent = await db.get(Agent, run.agent_id) if run.agent_id else None

    async def gen():
        pset = await load_principal_set(db, user)
        async for evt in stream_workflow(
            graph=graph, inputs=inputs, run_id=run_id, tenant_id=user.tenant_id, ps=pset,
            default_model_config_id=agent.model_config_id if agent else None,
            default_kb_ids=agent.kb_ids if agent else None,
            default_system=agent.system_prompt if agent else None,
            default_temperature=(agent.config or {}).get("temperature") if agent else None,
            approval=approval, resume=resume,
        ):
            etype = evt.get("type", "node")
            yield f"event: {etype}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
