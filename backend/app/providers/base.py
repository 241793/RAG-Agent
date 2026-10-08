"""模型 Provider 抽象层 —— 统一协议。

三类能力：LLM（对话）/ Embedding（向量）/ Rerank（重排）。
所有驱动实现同一接口，运行时可切换。本轮实现 openai 兼容 与 anthropi 两个驱动，
ollama / local_bge 留占位（本地部署时填）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class ToolCall:
    """LLM 发起的一次工具调用（非流式完整结果）。"""

    id: str
    name: str
    arguments: str = "{}"  # 原始 JSON 字符串，保持字符串避免解析失败丢信息


@dataclass
class ToolCallDelta:
    """流式增量工具调用分片（按 index 聚合）。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class ChatMessage:
    role: str  # system/user/assistant/tool
    content: str = ""
    images: list[dict] | None = None  # 多模态图片：[{url: "data:image/png;base64,..."}]
    tool_calls: list[ToolCall] | None = None  # assistant 发起工具调用时
    tool_call_id: str | None = None  # role=tool 回填时，对应 ToolCall.id
    name: str | None = None  # role=tool 时可选，函数名


@dataclass
class ChatResult:
    content: str = ""
    reasoning: str = ""  # 思考过程（DeepSeek-R1 / Claud thinking 等）
    usage: dict = field(default_factory=dict)
    model: str = ""
    finish_reason: str = "stop"  # stop | length | tool_calls | content_filter
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ChatChunk:
    delta: str = ""
    reasoning: str = ""  # 思考过程增量
    finish: bool = False
    usage: dict = field(default_factory=dict)
    tool_calls: list[ToolCallDelta] | None = None


@dataclass
class ProviderHealth:
    ok: bool
    message: str = ""
    latency_ms: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    async def chat(
        self, messages: list[ChatMessage], *, stream: bool = False, **kw
    ) -> ChatResult | AsyncIterator[ChatChunk]: ...

    async def health(self) -> ProviderHealth: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]: ...

    async def health(self) -> ProviderHealth: ...


@runtime_checkable
class RerankProvider(Protocol):
    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]: ...

    async def health(self) -> ProviderHealth: ...
