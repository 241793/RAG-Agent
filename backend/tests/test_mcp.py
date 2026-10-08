"""MCP 模块测试：工具桥接命名、内容归一化、stdio 命令白名单、http 客户端（MockTransport）、
resolve_tools 装配、权限码种子、管理 AI 工具注册。"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.agents.tools.registry import McpTool, build_mcp_tools
from app.core.errors import ValidationError
from app.services.mcp_client import McpClient, content_to_text
from app.services.mcp_manager import check_stdio_allowed


# ---- 工具桥接 ----
class _FakeServer:
    id = 7
    name = "My Server"
    tools_cache = [
        {"name": "read_file", "description": "读文件",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
        {"name": "search", "description": "搜索", "inputSchema": {"type": "object"}},
    ]


def test_build_mcp_tools_naming():
    seen: set[str] = set()
    tools = build_mcp_tools(_FakeServer(), seen=seen)
    names = [t.name for t in tools]
    assert names == ["mcp_my_server_read_file", "mcp_my_server_search"]
    assert tools[0].tool_name == "read_file"
    assert tools[0].required_permission == "mcp:invoke"
    assert tools[0].kind == "write"
    assert tools[0].parameters["properties"]["path"]["type"] == "string"


def test_build_mcp_tools_conflict_suffix():
    seen = {"mcp_my_server_read_file"}
    tools = build_mcp_tools(_FakeServer(), seen=seen)
    # 冲突项加 server_id 后缀
    assert "mcp_my_server_read_file_7" in [t.name for t in tools]


# ---- 内容归一化 ----
def test_content_to_text_text_blocks():
    r = {"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]}
    assert content_to_text(r) == "hello\nworld"


def test_content_to_text_non_text_and_structured():
    r = {"content": [{"type": "image", "mimeType": "image/png"}]}
    assert "[image:" in content_to_text(r)
    assert "structuredContent" not in content_to_text({"structuredContent": {"a": 1}})
    assert content_to_text({"structuredContent": {"a": 1}}) == '{"a": 1}'


def test_content_to_text_empty():
    assert content_to_text({}) == "(无输出)"
    assert content_to_text({"content": []}) == "(无输出)"


# ---- stdio 白名单 ----
def test_stdio_disabled_by_default(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "mcp_allow_stdio", False)
    with pytest.raises(ValidationError):
        check_stdio_allowed("python -m x")


def test_stdio_whitelist(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "mcp_allow_stdio", True)
    monkeypatch.setattr(settings, "mcp_stdio_allowed_cmds", "python,node,npx,uvx")
    check_stdio_allowed("python -m mcp_server")  # 不抛
    check_stdio_allowed("npx -y @x/server")
    check_stdio_allowed("node server.js")
    with pytest.raises(ValidationError):
        check_stdio_allowed("rm -rf /")
    with pytest.raises(ValidationError):
        check_stdio_allowed("bash -c x")


# ---- http 客户端（MockTransport）----
def test_http_client_tools_list_and_call(monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body["method"]
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                             "result": {"serverInfo": {"name": "ssl"}}})
        if method == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                             "result": {"tools": [{"name": "echo", "description": "回显",
                                                                   "inputSchema": {"type": "object"}}]}})
        if method == "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                             "result": {"content": [{"type": "text", "text": "pong"}]}})
        return httpx.Response(404)

    # 让 assert_safe_url 放行
    monkeypatch.setattr("app.connectors.http_guard.assert_safe_url", lambda *a, **k: None)

    async def _run():
        c = McpClient(transport="http", url="https://mcp.test/mcp")
        # 注入 mock transport（自建 client 的路径）
        orig_post = c._post

        async def _patched(client, target, bod):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mc:
                return await orig_post(mc, target, bod)

        c._post = _patched  # type: ignore[assignment]
        info = await c.initialize()
        assert info["serverInfo"]["name"] == "ssl"
        tools = await c.list_tools()
        assert tools[0]["name"] == "echo"
        result = await c.call_tool("echo", {"x": 1})
        assert content_to_text(result) == "pong"

    asyncio.new_event_loop().run_until_complete(_run())


def test_http_client_error_raises(monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                         "error": {"code": -32601, "message": "method not found"}})

    monkeypatch.setattr("app.connectors.http_guard.assert_safe_url", lambda *a, **k: None)

    async def _run():
        from app.services.mcp_client import McpError

        c = McpClient(transport="http", url="https://mcp.test/mcp")

        async def _direct(client, target, bod):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as mc:
                resp = await mc.post(target, json=bod)
                return resp.json()

        c._post = _direct  # type: ignore[assignment]
        with pytest.raises(McpError):
            await c.initialize()

    asyncio.new_event_loop().run_until_complete(_run())


# ---- 权限码种子 + AI 工具注册 ----
def test_mcp_permission_codes_seeded():
    from app.services.permission_seed import PERMISSIONS, ROLES

    codes = [p[0] for p in PERMISSIONS]
    for c in ("mcp:read", "mcp:manage", "mcp:invoke"):
        assert c in codes, f"缺少权限码 {c}"
    agent_admin = next(r for r in ROLES if r[0] == "agent_admin")
    assert "mcp:read" in agent_admin[3] and "mcp:invoke" in agent_admin[3]


def test_manage_mcp_server_tool_registered():
    from app.agents.tools.registry import registry

    t = registry.get_admin("manage_mcp_server")
    assert t is not None
    assert t.required_permission == "mcp:manage"
    assert t.kind == "write"
    assert "action" in t.parameters["properties"]


def test_import_skill_from_url_tool_uses_service():
    """修 bug 后：import_skill_from_url 不再引用不存在的 _import_from_url。"""
    from app.agents.tools.ops_tools2 import ImportSkillFromUrlTool

    t = ImportSkillFromUrlTool()
    assert t.required_permission == "skill:edit"
