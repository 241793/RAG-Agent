"""工作流新节点 + 审批恢复 + 事件字段测试。"""
from __future__ import annotations

import asyncio

from app.agents.workflow.engine import (
    NodeContext,
    WorkflowPaused,
    execute_graph,
)
from app.services.permission import PrincipalSet


def _ctx() -> NodeContext:
    return NodeContext(db=None, ps=PrincipalSet(user_id=1, tenant_id=1), run_id=1, tenant_id=1)


def _graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def test_variable_node():
    g = _graph(
        [
            {"id": "s", "type": "start", "data": {"inputs": [{"name": "q"}]}},
            {"id": "v", "type": "variable", "data": {"assignments": [{"name": "n", "value": "42"}]}},
            {"id": "e", "type": "end", "data": {"output": "n={{v.n}}"}},
        ],
        [{"source": "s", "target": "v"}, {"source": "v", "target": "e"}],
    )

    async def _t():
        final, _ = await execute_graph(g, {"q": "x"}, _ctx())
        assert final["output"] == "n=42"
    asyncio.new_event_loop().run_until_complete(_t())


def test_loop_node_template():
    g = _graph(
        [
            {"id": "s", "type": "start", "data": {"inputs": [{"name": "list", "default": [1, 2, 3]}]}},
            {"id": "lp", "type": "loop", "data": {"items": "{{s.list}}", "body": {"op": "template", "template": "n={{item}}"}}},
            {"id": "e", "type": "end", "data": {"output": "{{lp.output}}"}},
        ],
        [{"source": "s", "target": "lp"}, {"source": "lp", "target": "e"}],
    )

    async def _t():
        final, _ = await execute_graph(g, {"list": [1, 2, 3]}, _ctx())
        assert final["output"] == "n=1\nn=2\nn=3"
    asyncio.new_event_loop().run_until_complete(_t())


def test_loop_max_iterations():
    g = _graph(
        [
            {"id": "s", "type": "start", "data": {"inputs": [{"name": "list"}]}},
            {"id": "lp", "type": "loop", "data": {"items": "{{s.list}}", "max_iterations": 1, "body": {"op": "template", "template": "{{item}}"}}},
            {"id": "e", "type": "end", "data": {"output": "cnt={{lp.count}}"}},
        ],
        [{"source": "s", "target": "lp"}, {"source": "lp", "target": "e"}],
    )

    async def _t():
        final, _ = await execute_graph(g, {"list": [1, 2, 3, 4, 5]}, _ctx())
        assert final["output"] == "cnt=1"
    asyncio.new_event_loop().run_until_complete(_t())


def test_code_node():
    g = _graph(
        [
            {"id": "s", "type": "start", "data": {"inputs": [{"name": "q"}]}},
            {"id": "c", "type": "code", "data": {"code": "import sys, json\nprint(json.dumps({'output': 'hi-' + str(json.load(sys.stdin)['inputs'].get('q'))}))"}},
            {"id": "e", "type": "end", "data": {"output": "{{c.output}}"}},
        ],
        [{"source": "s", "target": "c"}, {"source": "c", "target": "e"}],
    )

    async def _t():
        final, _ = await execute_graph(g, {"q": "world"}, _ctx())
        assert final["output"] == "hi-world"
    asyncio.new_event_loop().run_until_complete(_t())


def test_approval_pause_and_resume():
    g = _graph(
        [
            {"id": "s", "type": "start", "data": {"inputs": [{"name": "q", "default": "x"}]}},
            {"id": "v", "type": "variable", "data": {"assignments": [{"name": "n", "value": "42"}]}},
            {"id": "ap", "type": "approval", "data": {"title": "确认"}},
            {"id": "e", "type": "end", "data": {"output": "ok={{ap.approved}} n={{v.n}}"}},
        ],
        [{"source": "s", "target": "v"}, {"source": "v", "target": "ap"}, {"source": "ap", "target": "e"}],
    )

    async def _t():
        ctx = _ctx()
        paused = None
        try:
            await execute_graph(g, {"q": "x"}, ctx)
        except WorkflowPaused as p:
            paused = p
        assert paused is not None and paused.node_id == "ap"
        assert paused.variables.get("v") == {"n": "42"}
        # 审批通过后从快照恢复（v 走重放）
        ctx.approval = {"ap": "approve"}
        final, records = await execute_graph(g, {"q": "x"}, ctx, resume={"variables": paused.variables})
        assert final["output"] == "ok=True n=42"
        assert [r for r in records if r["node_id"] == "v"][0].get("replayed") is True
    asyncio.new_event_loop().run_until_complete(_t())


def test_node_finished_carries_input_and_latency():
    g = _graph(
        [
            {"id": "s", "type": "start", "data": {"inputs": [{"name": "q"}]}},
            {"id": "v", "type": "variable", "data": {"assignments": [{"name": "n", "value": "1"}]}},
            {"id": "e", "type": "end", "data": {"output": "{{v.n}}"}},
        ],
        [{"source": "s", "target": "v"}, {"source": "v", "target": "e"}],
    )
    events: list[dict] = []

    async def emit(evt):
        events.append(evt)

    async def _t():
        ctx = _ctx()
        ctx.emit = emit
        await execute_graph(g, {"q": "x"}, ctx)
        fin = [e for e in events if e["type"] == "node_finished" and e["node_id"] == "v"][0]
        assert "input" in fin and "latency_ms" in fin
    asyncio.new_event_loop().run_until_complete(_t())
