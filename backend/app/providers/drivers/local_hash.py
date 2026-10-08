"""本地离线驱动（无需网络，用于管线自测 / 离线演示 / 无 key 时降级）。

local_hash: 基于词袋哈希的确定性向量。语义能力弱，仅用于验证检索流程或
极小规模离线场景；生产请使用云端或本地 bge 模型。
"""
from __future__ import annotations

import hashlib
import math
import re
import time

from app.providers.base import ChatChunk, ChatMessage, ChatResult, ProviderHealth

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]")


class LocalHashDriver:
    """确定性 bag-of-words 哈希向量。相同词越多，相似度越高。"""

    def __init__(self, *, dim: int = 1024) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
        for tok in tokens:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 16) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str], *, model: str | None = None, batch_size: int = 32) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def chat(self, messages: list[ChatMessage], *, model: str | None = None, stream: bool = False, **kw):
        """离线占位回复：把最后一条用户消息与参考片段拼接回显，用于无 key 演示。"""
        last = messages[-1].content if messages else ""
        answer = (
            "【离线模式回复】未配置云端对话模型。以下为检索到的上下文摘要，"
            "请在【模型管理】中配置 Provider 以获取真实回答。\n\n" + last[:800]
        )
        if stream:
            async def _gen():
                for ch in answer:
                    yield ChatChunk(delta=ch)
                yield ChatChunk(finish=True)

            return _gen()
        return ChatResult(content=answer, model="local-hash")

    async def health(self, **kw) -> ProviderHealth:
        return ProviderHealth(ok=True, message="本地离线驱动就绪", latency_ms=0)


class LocalHashRerankDriver:
    def __init__(self, *, dim: int = 1024) -> None:
        self._h = LocalHashDriver(dim=dim)

    async def rerank(self, query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
        qv = self._h._vector(query)
        scored = []
        for i, d in enumerate(docs):
            dv = self._h._vector(d)
            scored.append((i, sum(a * b for a, b in zip(qv, dv))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    async def health(self, **kw) -> ProviderHealth:
        return ProviderHealth(ok=True, message="本地重排就绪", latency_ms=0)
