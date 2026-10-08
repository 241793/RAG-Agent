"""连接器抽象 —— 与 providers/base.py 同风格（Protocol + dataclass）。

一个 KnowledgeConnector 代表一个外部 RAG 系统的检索入口。
- 模式 A（联邦实时检索）：实现 search/health。
- 模式 B（导入同步）：额外实现 list_documents（批量列举远端全量文档）。
  不具备批量列举能力的连接器可不实现，导入同步会退化为「按种子查询检索导入」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.providers.base import ProviderHealth


@dataclass
class ConnectorDoc:
    """外部系统返回的单条知识片段（已归一化）。"""

    content: str
    title: str | None = None
    score: float = 0.0
    page: int | None = None
    source_uri: str | None = None  # 原链，供引用溯源
    ref: str = ""                  # 全局唯一引用键（rrf 去重用），形如 "kb{kb_id}:{外部id}"


@runtime_checkable
class KnowledgeConnector(Protocol):
    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]: ...

    async def health(self) -> ProviderHealth: ...

    # 可选：批量列举远端文档（导入同步模式用）。未实现的连接器抛 NotImplementedError。
    async def list_documents(self, *, limit: int = 500) -> list[ConnectorDoc]:
        raise NotImplementedError
