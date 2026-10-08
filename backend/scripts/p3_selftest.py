"""P3 工作流端到端：含条件分支的 DAG，验证未命中分支被 skipped。"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.agents.workflow.engine import NodeContext, execute_graph
from app.core.db import AsyncSessionLocal, init_models
from app.services.permission import PrincipalSet

GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "data": {"inputs": [{"name": "x", "type": "integer", "default": 10}]}},
        {"id": "cond", "type": "condition", "data": {"expression": "{{start.x}} > 5"}},
        {"id": "hi", "type": "end", "data": {"output": "大于5，x={{start.x}}"}},
        {"id": "lo", "type": "end", "data": {"output": "小于等于5"}},
    ],
    "edges": [
        {"source": "start", "target": "cond"},
        {"source": "cond", "target": "hi", "sourceHandle": "true"},
        {"source": "cond", "target": "lo", "sourceHandle": "false"},
    ],
}


async def main() -> None:
    await init_models()
    async with AsyncSessionLocal() as db:
        ps = PrincipalSet(user_id=1, tenant_id=1, is_admin=True)
        # 场景1：x=10 → true 分支
        ctx = NodeContext(db=db, ps=ps, run_id=0, tenant_id=1, inputs={"x": 10})
        final, records = await execute_graph(GRAPH, {"x": 10}, ctx)
        status = {r["node_id"]: r["status"] for r in records}
        print(f"[1] x=10 输出={final.get('output')}")
        print(f"    hi={status.get('hi')} lo={status.get('lo')}")
        assert final["output"] == "大于5，x=10"
        assert status["hi"] == "success" and status["lo"] == "skipped"

        # 场景2：x=3 → false 分支
        ctx2 = NodeContext(db=db, ps=ps, run_id=0, tenant_id=1, inputs={})
        final2, records2 = await execute_graph(GRAPH, {"x": 3}, ctx2)
        status2 = {r["node_id"]: r["status"] for r in records2}
        print(f"[2] x=3 输出={final2.get('output')}")
        print(f"    hi={status2.get('hi')} lo={status2.get('lo')}")
        assert final2["output"] == "小于等于5"
        assert status2["lo"] == "success" and status2["hi"] == "skipped"

        print("\n✅ P3 工作流条件分支 + skipped 传播 通过")


if __name__ == "__main__":
    asyncio.run(main())
