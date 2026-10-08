"""文本切分器：fixed / recursive / parent_child。

父子分块：子块小(256-512 token)用于向量检索，命中后返回父块(1024-2048 token)给 LLM。
本实现以字符数近似 token（中文约 1 字 = 1 token，英文约 4 字符 = 1 token）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TextChunk:
    content: str
    ordinal: int
    page: int | None = None
    section: str | None = None
    chunk_type: str = "flat"  # parent/child/flat
    parent_index: int | None = None  # 指向同文档内父块的 ordinal
    parent_content: str | None = None
    is_parent: bool = False


# ---- 默认参数 ----
DEFAULT_PARENT_SIZE = 1500
DEFAULT_CHILD_SIZE = 400
DEFAULT_OVERLAP = 50


def chunk_text(
    text: str,
    *,
    strategy: str = "parent_child",
    child_size: int = DEFAULT_CHILD_SIZE,
    parent_size: int = DEFAULT_PARENT_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[TextChunk]:
    if strategy == "fixed":
        return _fixed(text, child_size, overlap)
    if strategy == "recursive":
        return _recursive(text, child_size, overlap)
    return _parent_child(text, child_size, parent_size, overlap)


def _fixed(text: str, size: int, overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    step = max(1, size - overlap)
    for i, start in enumerate(range(0, len(text), step)):
        seg = text[start : start + size]
        if seg.strip():
            chunks.append(TextChunk(content=seg.strip(), ordinal=i))
    return chunks


_SENT_SPLIT = re.compile(r"(?<=[。！？!?\n])")


def _recursive(text: str, size: int, overlap: int) -> list[TextChunk]:
    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    chunks: list[TextChunk] = []
    buf = ""
    ordinal = 0
    for s in sentences:
        if len(buf) + len(s) <= size:
            buf += s
        else:
            if buf.strip():
                chunks.append(TextChunk(content=buf.strip(), ordinal=ordinal))
                ordinal += 1
            if len(s) > size:
                for start in range(0, len(s), size - overlap):
                    sub = s[start : start + size]
                    if sub.strip():
                        chunks.append(TextChunk(content=sub.strip(), ordinal=ordinal))
                        ordinal += 1
                buf = ""
            else:
                buf = buf[-overlap:] + s if overlap else s
    if buf.strip():
        chunks.append(TextChunk(content=buf.strip(), ordinal=ordinal))
    return chunks


def _parent_child(text: str, child_size: int, parent_size: int, overlap: int) -> list[TextChunk]:
    """先切父块，再在父块内切子块。子块记录父块内容。"""
    parents = _recursive(text, parent_size, overlap)
    all_chunks: list[TextChunk] = []
    child_ordinal = 0
    for p_idx, parent in enumerate(parents):
        parent_ordinal = child_ordinal
        # 父块本身也作为一条记录（is_parent=True），但不参与向量检索
        all_chunks.append(
            TextChunk(
                content=parent.content,
                ordinal=parent_ordinal,
                chunk_type="parent",
                is_parent=True,
            )
        )
        child_ordinal += 1
        # 子块
        sub_chunks = _recursive(parent.content, child_size, overlap)
        for sub in sub_chunks:
            all_chunks.append(
                TextChunk(
                    content=sub.content,
                    ordinal=child_ordinal,
                    chunk_type="child",
                    parent_index=parent_ordinal,
                    parent_content=parent.content,
                )
            )
            child_ordinal += 1
    return all_chunks
