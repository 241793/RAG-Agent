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


# ---- 敏感操作分级与审计标记 ----
def test_tool_risk_level_and_sensitive():
    """风险分级：只读=0；写=2；dangerous（删除/密钥类）=3；敏感=>=2。"""
    from app.agents.tools.base import is_sensitive, tool_risk_level
    from app.agents.tools.registry import registry

    read = registry.get_builtin("knowledge_retrieval")
    write = registry.get_builtin("generate_file")
    danger = registry.get_admin("delete_kb")
    assert tool_risk_level(read) == 0 and not is_sensitive(read)
    assert tool_risk_level(write) == 2 and is_sensitive(write)
    assert tool_risk_level(danger) == 3 and is_sensitive(danger)


def test_risk_level_explicit_override():
    """显式 risk_level 覆盖推断。"""
    from app.agents.tools.base import is_sensitive, tool_risk_level

    class T:
        kind = "write"
        dangerous = True
        risk_level = 1  # 显式降级
    assert tool_risk_level(T()) == 1 and not is_sensitive(T())

    class D:
        kind = "read"
        dangerous = False
        risk_level = 3
    assert tool_risk_level(D()) == 3 and is_sensitive(D())


@pytest.mark.asyncio
async def test_react_loop_marks_autonomy_on_auto_write():
    """自动执行写操作 → on_audit 收到 autonomy='auto'；只读 → 'read'。"""
    from app.agents.react import run_react_loop
    from app.providers.base import ChatChunk, ToolCallDelta

    calls = []

    class FakeLLM:
        def __init__(self): self.n = 0
        async def chat(self, messages, **kw):
            self.n += 1
            async def gen1():
                yield ChatChunk(tool_calls=[
                    ToolCallDelta(index=0, id="t1", name="w", arguments_delta="{}"),
                    ToolCallDelta(index=1, id="t2", name="r", arguments_delta="{}"),
                ], finish=True)
            async def gen2():
                yield ChatChunk(delta="ok", finish=True)
            return gen1() if self.n == 1 else gen2()

    class WTool:
        name = "w"; description = "w"; required_permission = None; kind = "write"
        auto_approve = True; dangerous = True
        parameters = {"type": "object", "properties": {}}
        async def run(self, args, ctx): return ToolResult(content="wrote")

    class RTool:
        name = "r"; description = "r"; required_permission = None; kind = "read"
        parameters = {"type": "object", "properties": {}}
        async def run(self, args, ctx): return ToolResult(content="read")

    async def _audit(tc, result, denied, autonomy="read"):
        calls.append((tc.name, autonomy))

    class RM: model_name = "m"

    [e async for e in run_react_loop(
        db=None, ps=type("P", (), {"tenant_id": 1, "user_id": 1})(), perms={"*"},
        llm=FakeLLM(), rm=RM(), messages=[], tools=[WTool(), RTool()],
        max_turns=3, allow_auto_write=True, on_audit=_audit,
    )]
    by = dict(calls)
    assert by.get("w") == "auto", f"写工具应标 auto，实际 {by}"
    assert by.get("r") == "read", f"只读应标 read，实际 {by}"


@pytest.mark.asyncio
async def test_react_loop_marks_denied_autonomy():
    """无权限 → autonomy='denied'。"""
    from app.agents.react import run_react_loop
    from app.providers.base import ChatChunk, ToolCallDelta

    calls = []

    class FakeLLM:
        def __init__(self): self.n = 0
        async def chat(self, messages, **kw):
            self.n += 1
            async def gen1():
                yield ChatChunk(tool_calls=[ToolCallDelta(index=0, id="t1", name="sec", arguments_delta="{}")], finish=True)
            async def gen2():
                yield ChatChunk(delta="ok", finish=True)
            return gen1() if self.n == 1 else gen2()

    class SecTool:
        name = "sec"; description = "s"; required_permission = "admin:only"; kind = "read"
        parameters = {"type": "object", "properties": {}}
        async def run(self, args, ctx): return ToolResult(content="x")

    async def _audit(tc, result, denied, autonomy="read"):
        calls.append((tc.name, autonomy, denied))

    class RM: model_name = "m"

    [e async for e in run_react_loop(
        db=None, ps=type("P", (), {"tenant_id": 1, "user_id": 1})(), perms={"chat:use"},
        llm=FakeLLM(), rm=RM(), messages=[], tools=[SecTool()], max_turns=3, on_audit=_audit,
    )]
    assert calls and calls[0][1] == "denied" and calls[0][2] is True
