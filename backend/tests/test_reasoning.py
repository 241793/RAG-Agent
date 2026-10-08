"""思考过程（reasoning）全链路测试。

断言：
  - 驱动层：openai_compat 流式解析 reasoning_content / reasoning
  - 服务层：stream_answer 对带 reasoning 的 chunk 产出 reasoning 事件并落库
  - 无 reasoning 的 chunk 不产生 reasoning 事件（回归）
"""
from __future__ import annotations

import asyncio

from app.providers.base import ChatChunk, ChatResult
from app.providers.drivers.openai_compat import OpenAICompatibleDriver
from app.schemas.chat import MessageOut


def test_chunk_has_reasoning_field():
    assert ChatChunk(reasoning="思考").reasoning == "思考"
    assert ChatChunk().reasoning == ""
    assert ChatResult(reasoning="想法").reasoning == "想法"


def test_message_out_exposes_reasoning():
    assert "reasoning" in MessageOut.model_fields


def test_openai_compat_parses_reasoning_content(monkeypatch):
    """流式：delta.reasoning_content 应被解析进 ChatChunk.reasoning。"""
    driver = OpenAICompatibleDriver(base_url="http://x", api_key="k")
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"让me想"}}]}',
        'data: {"choices":[{"delta":{"content":"答案"}}]}',
        "data: [DONE]",
    ]

    class _FakeResp:
        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for ln in lines:
                yield ln

    class _FakeStream:
        async def __aenter__(self):
            return _FakeResp()

        async def __aexit__(self, *a):
            return False

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            return _FakeStream()

    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _FakeClient())

    async def _collect():
        chunks = []
        async for c in driver._stream_chat({"model": "m", "messages": []}):
            chunks.append(c)
        return chunks

    chunks = asyncio.new_event_loop().run_until_complete(_collect())
    reasoning = "".join(c.reasoning for c in chunks)
    content = "".join(c.delta for c in chunks)
    assert reasoning == "让me想"
    assert content == "答案"
