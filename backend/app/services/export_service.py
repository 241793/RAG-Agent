"""办公功能：会话导出（md/pdf/docx）与文档批量导出合并。

复用 file_tools 的渲染器（_render / _save_artifact）与 storage，避免重复实现。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def conversation_to_markdown(db: AsyncSession, *, conversation, user_id: int) -> str:
    """把会话渲染成 Markdown 文本（含角色、时间、引用）。"""
    from app.models import Message

    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id.asc())
        )
    ).scalars().all()
    lines = [f"# {conversation.title or '对话记录'}", ""]
    import time as _t

    for m in rows:
        ts = ""
        if m.created_at:
            ts = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(m.created_at / 1000))
        who = {"user": "👤 我", "assistant": "🤖 助手", "system": "⚙️ 系统"}.get(m.role, m.role)
        lines.append(f"## {who}  {ts}")
        lines.append(m.content or "")
        cites = m.citations or []
        if cites:
            lines.append("")
            lines.append("**参考来源：**")
            for c in cites[:5]:
                title = c.get("doc_title") or "文档"
                page = f"（第{c['page']}页）" if c.get("page") else ""
                lines.append(f"- {title}{page}")
        lines.append("")
    return "\n".join(lines)


async def export_conversation(
    db: AsyncSession, *, conversation, user_id: int, fmt: str = "md"
) -> tuple[str, bytes, str]:
    """导出会话为文件，返回 (filename, data, mime)。"""
    from app.agents.tools.file_tools import _render

    md = await conversation_to_markdown(db, conversation=conversation, user_id=user_id)
    safe_title = "".join(ch for ch in (conversation.title or "对话记录") if ch not in '\\/:*?"<>|')[:60]
    if fmt == "pdf":
        data, mime = _render({"format": "pdf", "content": md})
        return f"{safe_title}.pdf", data, mime
    if fmt == "docx":
        data, mime = _render({"format": "docx", "content": md})
        return f"{safe_title}.docx", data, mime
    return f"{safe_title}.md", md.encode("utf-8"), "text/markdown"


async def documents_to_markdown(db: AsyncSession, *, docs: list) -> str:
    """把多篇文档的内容/分块合并成一份 Markdown（用于批量导出合并）。"""
    from app.models import Chunk

    parts: list[str] = ["# 文档合并导出", ""]
    for doc in docs:
        parts.append(f"## {doc.title}")
        parts.append("")
        rows = (
            await db.execute(
                select(Chunk.content)
                .where(Chunk.doc_id == doc.id, Chunk.chunk_type != "parent")
                .order_by(Chunk.ordinal)
            )
        ).all()
        text = "\n\n".join(r[0] for r in rows) if rows else "（无内容）"
        parts.append(text)
        parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts)
