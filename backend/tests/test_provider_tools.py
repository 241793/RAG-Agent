"""Provider 工具调用单测（P0 硬前置验收）。

用 httpx.MockTransport 构造含 tool_calls 的响应，验证：
- openai_compat 驱动：非流式解析 tool_calls、流式解析 delta.tool_calls 增量
- anthropi 驱动：非流式解析 tool_use 块、流式 content_block_delta
- 请求侧序列化：assistant 的 tool_calls 与 tool 消息
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import ChatMessage, ToolCall
from app.providers.drivers.anthropi import AnthropiDriver
from app.providers.drivers.openai_compat import OpenAICompatibleDriver


# ============ openai_compat ============
def _openai_transport(resp_payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=resp_payload)

    return httpx.MockTransport(handler)


async def test_openai_serialize_tool_messages():
    msgs = [
        ChatMessage(role="user", content="hi"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="get_weather", arguments='{"city":"bj"}')],
        ),
        ChatMessage(role="tool", content="晴", tool_call_id="c1"),
    ]
    out = OpenAICompatibleDriver._serialize_messages(msgs)
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1]["role"] == "assistant"
    assert out[1]["tool_calls"][0]["id"] == "c1"
    assert out[1]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert out[2] == {"role": "tool", "tool_call_id": "c1", "content": "晴"}


async def test_openai_parse_tool_calls():
    payload = {
        "model": "gpt-4o",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {"name": "knowledge_retrieval", "arguments": '{"query":"x"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    drv = OpenAICompatibleDriver(base_url="http://test")
    transport = _openai_transport(payload)
    orig = httpx.AsyncClient

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = transport
            super().__init__(*a, **k)

    httpx.AsyncClient = PatchedClient
    try:
        res = await drv.chat([ChatMessage(role="user", content="hi")], model="gpt-4o")
    finally:
        httpx.AsyncClient = orig

    assert res.finish_reason == "tool_calls"
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].id == "call_abc"
    assert res.tool_calls[0].name == "knowledge_retrieval"
    assert json.loads(res.tool_calls[0].arguments)["query"] == "x"


async def test_openai_stream_tool_call_deltas():
    """流式：id/name 首帧，arguments 分片拼接。"""
    sse_lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"f","arguments":""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"a\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1}"}}]}}]}',
        "data: [DONE]",
    ]
    body = "\n\n".join(sse_lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    drv = OpenAICompatibleDriver(base_url="http://test")
    orig = httpx.AsyncClient

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    httpx.AsyncClient = PatchedClient
    try:
        acc: dict[int, dict] = {}
        stream = await drv.chat([ChatMessage(role="user", content="hi")], model="m", stream=True)
        async for chunk in stream:
            for d in chunk.tool_calls or []:
                slot = acc.setdefault(d.index, {"id": "", "name": "", "arguments": ""})
                if d.id:
                    slot["id"] = d.id
                if d.name:
                    slot["name"] = d.name
                slot["arguments"] += d.arguments_delta
    finally:
        httpx.AsyncClient = orig

    assert acc[0]["id"] == "c1"
    assert acc[0]["name"] == "f"
    assert acc[0]["arguments"] == '{"a":1}'


# ============ anthropi ============
async def test_anthropi_serialize_merges_tool_results():
    """多个工具结果必须合并进同一 user 轮。"""
    msgs = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="q"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="t1", name="f1", arguments='{"a":1}'),
                ToolCall(id="t2", name="f2", arguments="{}"),
            ],
        ),
        ChatMessage(role="tool", content="r1", tool_call_id="t1"),
        ChatMessage(role="tool", content="r2", tool_call_id="t2"),
    ]
    system, conv = AnthropiDriver._serialize_messages(msgs)
    assert system == "sys"
    # user(q) / assistant(tool_use x2) / user(tool_result x2)
    assert conv[0] == {"role": "user", "content": "q"}
    assert conv[1]["role"] == "assistant"
    blocks = conv[1]["content"]
    assert blocks[0]["type"] == "tool_use" and blocks[0]["input"] == {"a": 1}
    assert blocks[1]["type"] == "tool_use"
    # 两个 tool_result 合并在同一 user 轮
    assert conv[2]["role"] == "user"
    assert len(conv[2]["content"]) == 2
    assert conv[2]["content"][0]["type"] == "tool_result"
    assert conv[2]["content"][0]["tool_use_id"] == "t1"


async def test_anthropi_parse_tool_use():
    payload = {
        "model": "claud-x",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "我来查询。"},
            {"type": "tool_use", "id": "tu_1", "name": "knowledge_retrieval", "input": {"query": "y"}},
        ],
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    drv = AnthropiDriver(base_url="http://test")
    orig = httpx.AsyncClient

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    httpx.AsyncClient = PatchedClient
    try:
        res = await drv.chat([ChatMessage(role="user", content="hi")], model="claud-x")
    finally:
        httpx.AsyncClient = orig

    assert res.content == "我来查询。"
    assert res.finish_reason == "tool_calls"
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].id == "tu_1"
    assert json.loads(res.tool_calls[0].arguments)["query"] == "y"


async def test_anthropi_tools_to_claud():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查天气",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]
    out = AnthropiDriver._tools_to_claud(tools)
    assert out[0]["name"] == "get_weather"
    assert out[0]["input_schema"]["properties"]["city"]["type"] == "string"


async def test_anthropi_stream_tool_use():
    sse_lines = [
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu_1","name":"f"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"a\\":"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"1}"}}',
        'data: {"type":"message_stop"}',
    ]
    body = "\n\n".join(sse_lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    drv = AnthropiDriver(base_url="http://test")
    orig = httpx.AsyncClient

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    httpx.AsyncClient = PatchedClient
    try:
        acc: dict[int, dict] = {}
        stream = await drv.chat([ChatMessage(role="user", content="hi")], model="m", stream=True)
        async for chunk in stream:
            for d in chunk.tool_calls or []:
                slot = acc.setdefault(d.index, {"id": "", "name": "", "arguments": ""})
                if d.id:
                    slot["id"] = d.id
                if d.name:
                    slot["name"] = d.name
                slot["arguments"] += d.arguments_delta
    finally:
        httpx.AsyncClient = orig

    assert acc[0]["id"] == "tu_1"
    assert acc[0]["name"] == "f"
    assert acc[0]["arguments"] == '{"a":1}'
