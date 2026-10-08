"""连接器抽象 —— 与 providers/base.py 同风格（Protocol + dataclass）。

一个 KnowledgeConnector 代表一个外部 RAG 系统的检索入口。
模式 A（联邦实时检索）：只实现 search/health。
模式 B（导入同步，预留）：list_documents/fetch_document。
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
