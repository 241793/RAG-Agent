"""问答页工具调用测试：react 循环、工具装配、query_usage、权限过滤。"""
from __future__ import annotations

import pytest

from app.agents.tools.base import ToolContext, ToolResult


# ---- react 循环 ----
@pytest.mark.asyncio
async def test_react_loop_calls_tool_then_answers():
    from app.agents.react import run_react_loop
    from app.providers.base import ChatChunk, ToolCallDelta

    class FakeLLM:
        def __init__(self): self.n = 0
        async def chat(self, messages, **kw):
            self.n += 1
            # 第一次：发工具调用；第二次：终答
            async def gen1():
                yield ChatChunk(tool_calls=[ToolCallDelta(index=0, id="t1", name="echo", arguments_delta='{"x":1}')], finish=True)
            async def gen2():
                yield ChatChunk(delta="最终答案", finish=True)
            return gen1() if self.n == 1 else gen2()

    class EchoTool:
        name = "echo"
        description = "echo"
        required_permission = None
        kind = "read"
        parameters = {"type": "object", "properties": {}}
        async def run(self, args, ctx):
            return ToolResult(content=f"echo:{args.get('x')}")

    class RM:
        model_name = "m"

    evts = []
    async for e in run_react_loop(
        db=None, ps=type("P", (), {"tenant_id": 1, "user_id": 1})(), perms={"*"},
        llm=FakeLLM(), rm=RM(), messages=[], tools=[EchoTool()], max_turns=3,
    ):
        evts.append(e)
    types = [e["type"] for e in evts]
    assert "tool_call" in types and "tool_result" in types
    # 终答 delta 出现
    assert any(e["type"] == "delta" and "最终答案" in e.get("text", "") for e in evts)
    tr = next(e for e in evts if e["type"] == "tool_result")
    assert "echo:1" in tr["content"]


@pytest.mark.asyncio
async def test_react_loop_denies_unauthorized_tool():
    from app.agents.react import run_react_loop
    from app.providers.base import ChatChunk, ToolCallDelta

    class FakeLLM:
        def __init__(self): self.n = 0
        async def chat(self, messages, **kw):
            self.n += 1
            async def gen1():
                yield ChatChunk(tool_calls=[ToolCallDelta(index=0, id="t1", name="danger", arguments_delta="{}")], finish=True)
            async def gen2():
                yield ChatChunk(delta="done", finish=True)
            return gen1() if self.n == 1 else gen2()

    class DangerTool:
        name = "danger"; description = "d"; required_permission = "admin:only"; kind = "read"
        parameters = {"type": "object", "properties": {}}
        async def run(self, args, ctx): return ToolResult(content="SHOULD NOT RUN")

    class RM: model_name = "m"

    evts = [e async for e in run_react_loop(
        db=None, ps=type("P", (), {"tenant_id": 1, "user_id": 1})(), perms={"chat:use"},
        llm=FakeLLM(), rm=RM(), messages=[], tools=[DangerTool()], max_turns=3,
    )]
    tr = next(e for e in evts if e["type"] == "tool_result")
    assert tr["is_error"] and "无权限" in tr["content"]
    assert "SHOULD NOT RUN" not in tr["content"]


# ---- query_usage 工具 ----
@pytest.mark.asyncio
async def test_query_usage_tool_registered():
    from app.agents.tools.registry import registry

    t = registry.get_admin("query_usage")
    assert t is not None
    assert t.required_permission == "model:read"


@pytest.mark.asyncio
async def test_query_usage_returns_numbers():
    from app.core.db import AsyncSessionLocal, init_models
    from app.agents.tools.platform_tools import QueryUsageTool
    from app.agents.tools.base import ToolContext
    from app.services.permission import PrincipalSet

    await init_models()
    async with AsyncSessionLocal() as db:
        tool = QueryUsageTool()
        ctx = ToolContext(db=db, ps=PrincipalSet(user_id=1, tenant_id=1), tenant_id=1, user_id=1)
        res = await tool.run({"days": 1}, ctx)
        assert "总 token" in res.content
        assert isinstance(res.data.get("total_tokens"), int)


def test_platform_tools_registered():
    from app.agents.tools.registry import registry

    names = [t.name for t in registry.all_admin()]
    for must in ("query_usage", "list_users", "list_roles", "query_audit_logs",
                 "update_kb", "delete_document", "toggle_scheduled_task"):
        assert must in names, f"缺少工具：{must}"


def test_write_tools_have_summarize():
    from app.agents.tools.platform_tools import PLATFORM_TOOLS

    writes = [t for t in PLATFORM_TOOLS if getattr(t, "kind", "") == "write"]
    assert writes, "应有写操作工具"
    for t in writes:
        assert hasattr(t, "summarize")
        assert t.summarize({"kb_id": 1, "doc_id": 1, "task_id": 1, "user_id": 1, "name": "x", "enabled": True})


# ---- chat tool-confirm 端点 ----
def test_chat_tool_confirm_endpoint_registered():
    from app.api.v1.chat import router

    paths = {r.path for r in router.routes}
    assert "/chat/tool-confirm" in paths


def test_chat_request_has_tool_flags():
    from app.schemas.chat import ChatRequest

    r = ChatRequest(message="hi")
    assert r.use_tools is True
    assert r.allow_auto_write is False
    r2 = ChatRequest(message="hi", use_tools=False, allow_auto_write=True)
    assert r2.use_tools is False and r2.allow_auto_write is True
