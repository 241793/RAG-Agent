"""OpenAI 兼容驱动：覆盖 OpenAI / 第三方中转站 / vLLM / Ollama(/v1) 等。"""
from __future__ import annotations

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


class OpenAICompatibleDriver:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: int = 60,
        extra_headers: dict | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "sk-noauth"
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    @staticmethod
    def _serialize_messages(messages: list[ChatMessage]) -> list[dict]:
        """序列化消息，支持工具调用与工具结果。"""
        out: list[dict] = []
        for m in messages:
            if m.role == "tool":
                out.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
                )
            elif m.tool_calls:
                item: dict = {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments or "{}"},
                        }
                        for tc in m.tool_calls
                    ],
                }
                out.append(item)
            else:
                # 多模态：有图片时用 OpenAI vision 的 content 数组格式
                if m.images:
                    parts: list[dict] = []
                    if m.content:
                        parts.append({"type": "text", "text": m.content})
                    for img in m.images:
                        url = img.get("url") or img.get("image_url") or ""
                        parts.append({"type": "image_url", "image_url": {"url": url}})
                    out.append({"role": m.role, "content": parts})
                else:
                    out.append({"role": m.role, "content": m.content})
        return out

    # ---- LLM ----
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        stream: bool = False,
        **kw,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        payload = {
            "model": model,
            "messages": self._serialize_messages(messages),
            "stream": stream,
            **{k: v for k, v in kw.items() if v is not None},
        }
        if stream:
            return self._stream_chat(payload)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=(tc.get("function") or {}).get("arguments") or "{}",
            )
            for tc in (message.get("tool_calls") or [])
        ]
        return ChatResult(
            content=message.get("content") or "",
            reasoning=message.get("reasoning_content") or message.get("reasoning") or "",
            usage=data.get("usage") or {},
            model=data.get("model", model),
            finish_reason=choice.get("finish_reason", "stop"),
            tool_calls=tool_calls,
        )

    async def list_models(self) -> list[dict]:
        """拉取 Provider 提供的模型列表（GET /v1/models）。"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        items = data.get("data") if isinstance(data, dict) else data
        out: list[dict] = []
        for it in items or []:
            if isinstance(it, dict):
                out.append({"id": it.get("id") or it.get("name"), "owned_by": it.get("owned_by", "")})
            elif isinstance(it, str):
                out.append({"id": it})
        return out

    async def _stream_chat(self, payload: dict) -> AsyncIterator[ChatChunk]:
        import json

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        yield ChatChunk(finish=True)
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    usage = obj.get("usage") or {}
                    deltas: list[ToolCallDelta] = []
                    for tc in delta.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        deltas.append(
                            ToolCallDelta(
                                index=tc.get("index", 0),
                                id=tc.get("id"),
                                name=fn.get("name"),
                                arguments_delta=fn.get("arguments") or "",
                            )
                        )
                    yield ChatChunk(
                        delta=delta.get("content") or "",
                        reasoning=delta.get("reasoning_content") or delta.get("reasoning") or "",
                        usage=usage,
                        tool_calls=deltas or None,
                    )

    # ---- Embedding ----
    async def embed(self, texts: list[str], *, model: str, batch_size: int = 32) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                try:
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        json={"model": model, "input": batch},
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    from app.core.errors import UpstreamError

                    raise UpstreamError(
                        "调用 /embeddings 失败", base_url=self.base_url, model=model,
                        status_code=e.response.status_code,
                        raw=(e.response.text or "")[:500], purpose="embedding",
                    ) from e
                except httpx.RequestError as e:
                    from app.core.errors import UpstreamError

                    raise UpstreamError(
                        f"无法连接上游：{type(e).__name__}", base_url=self.base_url, model=model,
                        purpose="embedding",
                    ) from e
                data = resp.json()
                # 按 index 排序确保顺序
                items = sorted(data["data"], key=lambda x: x["index"])
                out.extend([it["embedding"] for it in items])
        return out

    # ---- Rerank（部分兼容服务提供 /rerank）----
    async def rerank(self, query: str, docs: list[str], *, model: str, top_n: int) -> list[tuple[int, float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/rerank",
                json={"model": model, "query": query, "documents": docs, "top_n": top_n},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results") or data.get("data") or []
        return [(r["index"], r.get("relevance_score", r.get("score", 0.0))) for r in results]

    # ---- Health ----
    async def health(self, *, model: str | None = None, purpose: str = "chat") -> ProviderHealth:
        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if purpose == "embedding":
                    resp = await client.post(
                        f"{self.base_url}/embeddings",
                        json={"model": model, "input": ["ping"]},
                        headers=self._headers(),
                    )
                else:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
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
