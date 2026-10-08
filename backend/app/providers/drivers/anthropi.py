"""Anthropi (Claud) 驱动。

Anthropi Messages API 与 OpenAI 略有差异：
- endpoint: /v1/messages
- system 单独字段；messages 只含 user/assistant
- 工具调用用 tool_use / tool_result 内容块（input 为对象，非字符串）
- 工具结果必须合并进同一 user 轮
- 流式事件：content_block_delta / content_block_start(tool_use) / input_json_delta
- 鉴权头：x-api-key + anthropi-version
"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator

import httpx

from app.providers.base import (
    ChatChunk,
    ChatMessage,
    ChatResult,
    ProviderHealth,
    ToolCall,
    ToolCallDelta,
)

ANTHROPI_VERSION = "2023-06-01"


class AnthropiDriver:
    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropi.com",
        api_key: str | None = None,
        timeout: int = 60,
        extra_headers: dict | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropi-version": ANTHROPI_VERSION,
            **self.extra_headers,
        }

    @staticmethod
    def _serialize_messages(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        """转 Claud Messages 格式。

        关键：连续的工具结果必须合并进同一个 user 轮的 content 块列表，
        且 assistant 的工具调用用 tool_use 块（input 为对象）。
        """
        system = "\n".join(m.content for m in messages if m.role == "system")
        conv: list[dict] = []
        pending_results: list[dict] = []

        def flush_results() -> None:
            if pending_results:
                conv.append({"role": "user", "content": pending_results[:]})
                pending_results.clear()

        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                pending_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                )
                continue
            flush_results()
            if m.role == "assistant" and m.tool_calls:
                blocks: list[dict] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    try:
                        inp = json.loads(tc.arguments or "{}")
                    except json.JSONDecodeError:
                        inp = {}
                    blocks.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": inp}
                    )
                conv.append({"role": "assistant", "content": blocks})
            else:
                conv.append({"role": m.role, "content": m.content})
        flush_results()
        return system, conv

    @staticmethod
    def _tools_to_claud(tools: list[dict] | None) -> list[dict] | None:
        """OpenAI 风格 tools → Claud tools（parameters → input_schema）。"""
        if not tools:
            return None
        out = []
        for t in tools:
            fn = t.get("function") or {}
            out.append(
                {
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return out

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        stream: bool = False,
        max_tokens: int = 2048,
        temperature: float | None = None,
        tools: list[dict] | None = None,
        **kw,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        system, conv = self._serialize_messages(messages)
        payload: dict = {
            "model": model,
            "messages": conv,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature
        claud_tools = self._tools_to_claud(tools)
        if claud_tools:
            payload["tools"] = claud_tools

        if stream:
            return self._stream_chat(payload)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/v1/messages", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        thinking = "".join(
            b.get("thinking", "") for b in blocks if b.get("type") in ("thinking", "redacted_thinking")
        )
        tool_calls = [
            ToolCall(
                id=b.get("id", ""),
                name=b.get("name", ""),
                arguments=json.dumps(b.get("input") or {}, ensure_ascii=False),
            )
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        stop_reason = data.get("stop_reason", "stop")
        return ChatResult(
            content=text,
            reasoning=thinking,
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
            },
            model=data.get("model", model),
            finish_reason="tool_calls" if stop_reason == "tool_use" else stop_reason,
            tool_calls=tool_calls,
        )

    async def _stream_chat(self, payload: dict) -> AsyncIterator[ChatChunk]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/messages", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    etype = obj.get("type")
                    if etype == "content_block_start":
                        block = obj.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            yield ChatChunk(
                                tool_calls=[
                                    ToolCallDelta(
                                        index=obj.get("index", 0),
                                        id=block.get("id"),
                                        name=block.get("name"),
                                        arguments_delta="",
                                    )
                                ]
                            )
                    elif etype == "content_block_delta":
                        delta = obj.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield ChatChunk(delta=delta.get("text", ""))
                        elif delta.get("type") == "thinking_delta":
                            yield ChatChunk(reasoning=delta.get("thinking", ""))
                        elif delta.get("type") == "input_json_delta":
                            yield ChatChunk(
                                tool_calls=[
                                    ToolCallDelta(
                                        index=obj.get("index", 0),
                                        arguments_delta=delta.get("partial_json", ""),
                                    )
                                ]
                            )
                    elif etype == "message_delta":
                        usage = obj.get("usage") or {}
                        yield ChatChunk(usage={"completion_tokens": usage.get("output_tokens", 0)})
                    elif etype == "message_stop":
                        yield ChatChunk(finish=True)
                        break

    async def embed(self, texts: list[str], *, model: str, batch_size: int = 32) -> list[list[float]]:
        raise NotImplementedError("Anthropi 不提供 embedding 接口，请配置其他向量 Provider")

    async def health(self, *, model: str | None = None, purpose: str = "chat") -> ProviderHealth:
        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/messages",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                    headers=self._headers(),
                )
            latency = int((time.time() - t0) * 1000)
            if resp.status_code < 400:
                return ProviderHealth(ok=True, message="连接正常", latency_ms=latency)
            return ProviderHealth(ok=False, message=f"HTTP {resp.status_code}: {resp.text[:200]}", latency_ms=latency)
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:200])
