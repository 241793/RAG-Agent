"""上下文压缩：超阈值时把早期对话摘要写入 Conversation.summary，保留最近 N 条原文。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.providers.base import ChatMessage
from app.services.token_est import estimate_messages

logger = get_logger("context")

SUMMARY_SYSTEM = (
    "你是一个对话摘要器。把下面的多轮对话压缩成简洁的中文摘要，"
    "保留关键事实、结论、用户偏好与待办事项，不要遗漏人名/实体名与数字。只输出摘要本身。"
)
THRESHOLD_TOKENS = 4000
KEEP_RECENT = 6


async def maybe_compress(db: AsyncSession, conversation_id: int) -> bool:
    """若对话历史超阈值则压缩早期消息。返回是否执行了压缩。"""
    from app.models import Conversation, Message

    conv = await db.get(Conversation, conversation_id)
    if not conv:
        return False
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role.in_(("user", "assistant")))
            .order_by(Message.id.asc())
        )
    ).scalars().all()
    if len(rows) <= KEEP_RECENT:
        return False
    if estimate_messages(rows) < THRESHOLD_TOKENS:
        return False

    # 待摘要的早期消息：水位之后、最近 N 条之前
    watermark = conv.summary_upto_message_id or 0
    to_summarize = [m for m in rows[:-KEEP_RECENT] if m.id > watermark]
    if not to_summarize:
        return False

    transcript = "\n".join(f"{m.role}: {m.content}" for m in to_summarize)
    prev = conv.summary or ""
    prompt = (f"已有摘要：\n{prev}\n\n" if prev else "") + f"新增对话：\n{transcript}"

    try:
        from app.providers.registry import get_llm

        llm, rm = await get_llm(db, tenant_id=conv.tenant_id)
        res = await llm.chat(
            [ChatMessage(role="system", content=SUMMARY_SYSTEM), ChatMessage(role="user", content=prompt)],
            model=rm.model_name, stream=False, temperature=0.2,
        )
        summary = (res.content or "").strip()
    except Exception:  # noqa: BLE001
        logger.exception("context_compress_failed", conversation_id=conversation_id)
        return False

    if not summary:
        return False
    conv.summary = summary
    conv.summary_upto_message_id = to_summarize[-1].id
    await db.commit()
    logger.info("context_compressed", conversation_id=conversation_id, upto=to_summarize[-1].id)
    return True


async def load_context(db: AsyncSession, conversation, limit: int = KEEP_RECENT) -> tuple[str | None, list[ChatMessage]]:
    """返回 (摘要块, 最近 N 条历史消息)。"""
    from app.models import Message

    summary = None
    watermark = 0
    if conversation is not None:
        summary = getattr(conversation, "summary", None)
        watermark = getattr(conversation, "summary_upto_message_id", 0) or 0
    if conversation is None:
        return None, []
    cond = [Message.conversation_id == conversation.id, Message.role.in_(("user", "assistant"))]
    if watermark:
        cond.append(Message.id > watermark)
    rows = (
        await db.execute(select(Message).where(*cond).order_by(Message.id.desc()).limit(limit))
    ).scalars().all()
    history = [ChatMessage(role=m.role, content=m.content) for m in reversed(rows) if m.content]
    summary_block = f"[历史对话摘要]\n{summary}" if summary else None
    return summary_block, history


async def _compress_job(conversation_id: int) -> None:
    """队列任务：独立 session 执行压缩。"""
    from app.core.db import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await maybe_compress(db, conversation_id)
    except Exception:  # noqa: BLE001
        logger.exception("context_compress_job_failed", conversation_id=conversation_id)
