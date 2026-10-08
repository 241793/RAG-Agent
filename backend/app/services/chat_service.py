"""对话服务：检索增强生成（RAG）+ 引用溯源。"""
from __future__ import annotations

import time
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.models import Conversation, Message, UsageLog
from app.providers.base import ChatMessage
from app.providers.registry import get_llm
from app.schemas.chat import Citation, RetrievedChunk
from app.services.permission import PrincipalSet
from app.services.retrieval_service import retrieve, to_citations

logger = get_logger("chat")

# 防幻觉核心：要求明确区分【知识库资料】与【模型自身知识】，不得混淆来源。
SYSTEM_PROMPT = """你是企业知识助手。回答时**必须明确区分**两类信息来源，绝不可混淆：

一、来自【参考资料】（企业知识库）：
- 直接依据资料作答，并在相应句子后用 [1] [2] 标注引用编号，编号须与资料条目一致。
- 引用编号只能来自资料，**不得编造或给自身知识标注编号**。

二、来自你自身知识（资料未覆盖 / 无关 / 缺失时）：
- 先在回答开头用一句话明确声明「以下内容不在知识库中，为模型自身知识：」，然后作答。
- **绝不把自身知识伪装成知识库内容**。

三、资料与自身知识冲突时：以资料为准，并简述冲突点。
四、资料完全无法回答时：明确说明「知识库中未找到相关信息」，再按需补充自身知识建议。
五、回答使用简体中文，条理清晰。"""

# 纯聊天（关闭知识库检索）时使用
PLAIN_SYSTEM_PROMPT = "你是一个乐于助人的智能助手。请用简体中文，条理清晰地回答用户问题。"


def _build_context(chunks: list[RetrievedChunk]) -> tuple[str, list[Citation]]:
    if not chunks:
        return (
            "（本次未检索到相关企业资料。请在回答开头明确说明「知识库中未找到相关内容」；"
            "如需补充自身知识请注明，且不得标注任何 [n] 引用。）",
            [],
        )
    from app.core.config import settings

    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        src = f"{c.doc_title or '未知文档'}"
        if c.page:
            src += f" 第{c.page}页"
        parts.append(f"[{i}] 来源：{src}\n{c.content}")
    body = "\n\n".join(parts)
    # 纵深防御：给检索内容加边界标记，降低间接注入影响
    if settings.security_guard_enabled and settings.security_guard_wrap_context:
        from app.services.security_guard import wrap_untrusted

        body = wrap_untrusted(body)
    return body, to_citations(chunks)


def guard_check(text: str):
    """对输入/内容做安全检查，返回 GuardResult 或 None（未启用时）。"""
    from app.core.config import settings

    if not settings.security_guard_enabled:
        return None
    from app.services.security_guard import detect

    sensitive = [w.strip() for w in settings.security_guard_sensitive_words.split(",") if w.strip()]
    return detect(
        text,
        extra_sensitive=sensitive,
        block_threshold=settings.security_guard_block_threshold,
        flag_threshold=settings.security_guard_flag_threshold,
    )


async def get_or_create_conversation(
    db: AsyncSession, *, user_id: int, tenant_id: int, conversation_id: int | None, kb_ids: list[int], title: str | None
) -> Conversation:
    if conversation_id:
        conv = await db.get(Conversation, conversation_id)
        if conv and conv.user_id == user_id:
            if kb_ids:
                conv.kb_ids = kb_ids
            return conv
    conv = Conversation(
        tenant_id=tenant_id,
        user_id=user_id,
        title=title or "新对话",
        kb_ids=kb_ids or [],
    )
    db.add(conv)
    await db.flush()
    return conv


async def _history(db: AsyncSession, conversation_id: int, limit: int = 6) -> list[ChatMessage]:
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    msgs = [ChatMessage(role=m.role, content=m.content) for m in reversed(rows) if m.role in ("user", "assistant")]
    return msgs


async def prepare(
    db: AsyncSession,
    *,
    ps: PrincipalSet,
    body_kb_ids: list[int],
    query: str,
    top_k: int,
    images: list[dict] | None = None,
    use_retrieval: bool = True,
    score_threshold: float = 0.0,
    history: list[ChatMessage] | None = None,
    summary: str | None = None,
) -> tuple[list[ChatMessage], list[RetrievedChunk], list[Citation]]:
    """检索 + 组装消息。返回 (messages, chunks, citations)。

    body_kb_ids 为空时自动检索全部有权知识库（权限过滤内建）。
    images 为多模态图片（视觉模型用）。
    use_retrieval=False 时跳过检索，走纯聊天（用模型自身知识回答）。
    history/summary：多轮上下文（摘要在前，最近 N 条在后）。
    """
    hist = list(history or [])
    cap_brief = await _capability_brief(db, ps, query=query)
    if not use_retrieval:
        messages = [ChatMessage(role="system", content=PLAIN_SYSTEM_PROMPT)]
        if cap_brief:
            messages.append(ChatMessage(role="system", content=cap_brief))
        if summary:
            messages.append(ChatMessage(role="system", content=f"[历史对话摘要]\n{summary}"))
        messages.extend(hist)
        messages.append(ChatMessage(role="user", content=query, images=images or None))
        return messages, [], []

    from app.services.retrieval_service import condense_query

    # 多轮追问：结合历史改写检索用 query（喂给 LLM 的仍是原文）
    retrieval_query = await condense_query(db, tenant_id=ps.tenant_id, query=query, history=hist)
    resp = await retrieve(
        db, ps=ps, query=retrieval_query, kb_ids=body_kb_ids or None, top_k=top_k, score_threshold=score_threshold
    )
    context, citations = _build_context(resp.chunks)
    messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    if cap_brief:
        messages.append(ChatMessage(role="system", content=cap_brief))
    if summary:
        messages.append(ChatMessage(role="system", content=f"[历史对话摘要]\n{summary}"))
    messages.extend(hist)
    messages.append(ChatMessage(role="user", content=f"【参考资料】\n{context}\n\n【用户问题】\n{query}", images=images or None))
    return messages, resp.chunks, citations


async def _capability_brief(db: AsyncSession, ps: PrincipalSet, *, query: str = "") -> str:
    """平台能力摘要（可开关）。默认只给极短横幅；仅当 query 命中"能力/权限"类问法才给完整摘要。"""
    from app.core.config import settings

    if not getattr(settings, "inject_capabilities_default", True):
        return ""
    try:
        from app.agents.capabilities import (
            build_capability_banner, build_capability_brief, is_capability_query,
        )

        is_admin = bool(getattr(ps, "is_admin", False))
        if not is_capability_query(query):
            return build_capability_banner(is_admin)
        from app.middleware.auth_dep import get_user_permission_codes
        from app.models import User

        u = await db.get(User, ps.user_id) if ps.user_id else None
        perms = await get_user_permission_codes(db, u) if u else set()
        return await build_capability_brief(
            db, perms=perms, is_admin=is_admin, tenant_id=ps.tenant_id
        )
    except Exception:  # noqa: BLE001
        return ""


async def stream_answer(
    db: AsyncSession,
    *,
    ps: PrincipalSet,
    conversation: Conversation,
    query: str,
    top_k: int,
    model_config_id: int | None = None,
    temperature: float | None = None,
    images: list[dict] | None = None,
    attachments: list[dict] | None = None,
    use_retrieval: bool = True,
    use_tools: bool = False,
    allow_auto_write: bool = False,
    request=None,
) -> AsyncIterator[dict]:
    """流式生成。yield 事件字典：{type: meta|delta|citations|usage|done|error}"""
    t0 = time.time()
    # 先取上下文历史（务必在落当前用户消息之前，否则会把本轮算进历史）
    from app.services.context_service import load_context

    summary, history = await load_context(db, conversation)
    # 落用户消息
    user_msg = Message(
        tenant_id=ps.tenant_id,
        conversation_id=conversation.id,
        role="user",
        content=query,
        attachments=attachments or None,
        created_at=int(time.time() * 1000),
    )
    db.add(user_msg)
    conversation.message_count = (conversation.message_count or 0) + 1
    await db.commit()

    yield {"type": "meta", "conversation_id": conversation.id}

    # 内容安全：输入侧检测（高风险直接拦截）
    g = guard_check(query)
    if g and g.blocked:
        yield {"type": "error", "message": f"输入被安全策略拦截（{g.risk_level}）: {g.summary()}"}
        yield {"type": "done", "blocked": True}
        return

    messages, chunks, citations = await prepare(
        db, ps=ps, body_kb_ids=conversation.kb_ids or [], query=query, top_k=top_k,
        images=images, use_retrieval=use_retrieval, history=history, summary=summary,
    )

    llm, rm = await get_llm(db, tenant_id=ps.tenant_id, config_id=model_config_id)
    temp = temperature if temperature is not None else 0.2
    collected = ""
    collected_reasoning = ""
    usage: dict = {}
    suspended_action_id: int | None = None

    # 工具装配（按权限过滤）：仅当 use_tools 时走 ReAct 循环
    # 只常驻核心工具（内置+文件+办公）；管理/运维工具改为按需路由（find_tools），省 token
    tools: list = []
    dynamic_tools: dict = {}
    perms_set: set[str] = set()
    if use_tools:
        try:
            from app.agents.tools.registry import registry as _reg
            from app.agents.tools.registry import resolve_admin_pool, resolve_tools
            from app.middleware.auth_dep import get_user_permission_codes
            from app.models import User

            u = await db.get(User, ps.user_id) if ps.user_id else None
            perms_set = await get_user_permission_codes(db, u) if u else set()
            _cfg = {"builtin": {}}
            for t in _reg.all_builtin():
                _cfg["builtin"][t.name] = {"enabled": True}
            tools = await resolve_tools(
                db, tool_config=_cfg, skill_ids=[], tenant_id=ps.tenant_id, perms=perms_set,
                is_external=bool(getattr(ps, "is_external", False)),
            )
            dynamic_tools = resolve_admin_pool(
                perms=perms_set, is_external=bool(getattr(ps, "is_external", False)),
            )
        except Exception:  # noqa: BLE001
            logger.exception("resolve_tools_failed")

    try:
        if tools:
            # —— 工具循环（问答页拥有全部功能）——
            from app.agents.react import run_react_loop

            async def _pending(tool, tc, args):
                # 问答页写操作 → 落 AgentAction（agent_id 可空）
                import uuid as _uuid

                from app.models import AgentAction

                summary = ""
                if hasattr(tool, "summarize"):
                    try:
                        summary = tool.summarize(args)
                    except Exception:  # noqa: BLE001
                        summary = f"将调用 {tool.name}"
                action = AgentAction(
                    tenant_id=ps.tenant_id, conversation_id=conversation.id, agent_id=None,
                    user_id=ps.user_id, tool_name=tool.name, tool_kind="write",
                    arguments=args,
                    raw_tool_call={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                    summary=summary, status="pending", idempotency_key=_uuid.uuid4().hex,
                    expires_at=int(time.time() * 1000) + 10 * 60 * 1000,
                )
                db.add(action)
                await db.commit()
                return action

            async def _audit(tc, result, denied):
                try:
                    from app.services.audit_service import record_audit

                    record_audit(
                        db, action="chat.tool_call", resource_type="tool", resource_id=tc.name,
                        after={"arguments": tc.arguments[:1000], "is_error": result.is_error,
                               "latency_ms": result.latency_ms, "conversation_id": conversation.id},
                        result="failure" if (denied or result.is_error) else "success",
                        error="permission_denied" if denied else None,
                        tenant_id=ps.tenant_id, actor_id=ps.user_id, actor_type="user",
                    )
                except Exception:  # noqa: BLE001
                    pass

            async for evt in run_react_loop(
                db=db, ps=ps, perms=perms_set, llm=llm, rm=rm, messages=messages,
                tools=tools, dynamic_tools=dynamic_tools, conversation_id=conversation.id,
                temperature=temp, max_turns=6, allow_auto_write=allow_auto_write,
                on_audit=_audit, on_pending_action=(None if allow_auto_write else _pending),
            ):
                t = evt.get("type")
                if t == "delta":
                    collected += evt.get("text", "")
                    yield evt
                elif t == "reasoning":
                    collected_reasoning += evt.get("text", "")
                    yield evt
                elif t == "usage":
                    usage.update(evt.get("usage") or {})
                    yield evt
                elif t == "_suspended":
                    suspended_action_id = evt.get("action_id")
                    yield {"type": "done", "message_id": None, "suspended": True}
                    return
                else:
                    yield evt
        else:
            # —— 无工具：原单轮路径 ——
            stream = await llm.chat(messages, model=rm.model_name, stream=True, temperature=temp)
            async for chunk in stream:
                if request is not None:
                    try:
                        if await request.is_disconnected():
                            break
                    except Exception:  # noqa: BLE001
                        pass
                if chunk.reasoning:
                    collected_reasoning += chunk.reasoning
                    yield {"type": "reasoning", "text": chunk.reasoning}
                if chunk.delta:
                    collected += chunk.delta
                    yield {"type": "delta", "text": chunk.delta}
                if chunk.usage:
                    usage.update(chunk.usage)
                if chunk.finish:
                    break
    except Exception as e:  # noqa: BLE001
        logger.exception("llm_stream_failed")
        yield {"type": "error", "message": str(e)[:300]}

    latency = int((time.time() - t0) * 1000)
    yield {"type": "citations", "citations": [c.model_dump() for c in citations]}

    # 归一化 usage（统一契约：prompt/completion/total/cached）
    from app.services.usage_service import normalize_usage

    norm = normalize_usage(usage)

    # 落助手消息
    asst = Message(
        tenant_id=ps.tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=collected,
        reasoning=collected_reasoning or None,
        citations=[c.model_dump() for c in citations],
        usage=norm,
        model=rm.model_name,
        latency_ms=latency,
        created_at=int(time.time() * 1000),
    )
    db.add(asst)
    conversation.message_count = (conversation.message_count or 0) + 1
    db.add(
        UsageLog(
            tenant_id=ps.tenant_id,
            user_id=ps.user_id,
            conversation_id=conversation.id,
            model_config_id=rm.config_id,
            purpose="chat",
            prompt_tokens=norm["prompt_tokens"],
            completion_tokens=norm["completion_tokens"],
            total_tokens=norm["total_tokens"],
            cached_tokens=norm["cached_tokens"],
            latency_ms=latency,
            success=True,
            created_at=int(time.time() * 1000),
        )
    )
    await db.commit()
    # 异步触发上下文压缩（不阻塞响应）
    _schedule_compress(conversation.id, history)

    # 引用一致性校验（防幻觉：检测编造的引用编号）
    try:
        from app.services.citation_check import check as _cite_check

        cc = _cite_check(collected, [c.model_dump() for c in citations])
        if cc["has_fake_cite"]:
            yield {"type": "citation_check", "warning": "答案包含可能不实的引用编号", **cc}
    except Exception:  # noqa: BLE001
        pass

    yield {"type": "usage", "usage": norm, "latency_ms": latency}
    yield {"type": "done", "message_id": asst.id}


def _schedule_compress(conversation_id: int, history: list[ChatMessage]) -> None:
    try:
        from app.services.context_service import THRESHOLD_TOKENS, _compress_job
        from app.services.token_est import estimate_messages
        from app.tasks.queue import submit

        if estimate_messages(history) + 200 >= THRESHOLD_TOKENS:
            submit(f"compress:{conversation_id}", lambda: _compress_job(conversation_id))
    except Exception:  # noqa: BLE001
        logger.exception("schedule_compress_failed")


async def resume_answer(
    db: AsyncSession,
    *,
    ps: PrincipalSet,
    action,  # AgentAction（status 已置 approved）
    tool,    # 已执行的工具实例
    tool_result_text: str,
    allow_auto_write: bool = False,
) -> AsyncIterator[dict]:
    """问答页 HITL：确认并执行写工具后，把工具结果回灌 LLM 续跑剩余轮次。

    messages 跨请求需重建：system(能力摘要) + 历史 + assistant(tool_calls) + tool(result)。
    续跑仍走 run_react_loop（可继续调用更多工具或最终作答），并把助手消息落库。
    """
    from app.agents.react import run_react_loop
    from app.agents.tools.registry import registry as _reg
    from app.agents.tools.registry import resolve_admin_pool, resolve_tools
    from app.middleware.auth_dep import get_user_permission_codes
    from app.models import User
    from app.providers.base import ToolCall as _ToolCall
    from app.services.context_service import load_context

    t0 = time.time()
    conv = await db.get(Conversation, action.conversation_id) if action.conversation_id else None
    if conv is None:
        yield {"type": "error", "message": "会话不存在，无法续跑"}
        return

    summary, history = await load_context(db, conv)
    last_user_q = next((m.content for m in reversed(history) if m.role == "user"), "")
    cap_brief = await _capability_brief(db, ps, query=last_user_q)

    messages: list[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    if cap_brief:
        messages.append(ChatMessage(role="system", content=cap_brief))
    if summary:
        messages.append(ChatMessage(role="system", content=summary))
    messages.extend(history)
    raw = action.raw_tool_call or {}
    call_id = raw.get("id", f"call_{action.id}")
    messages.append(ChatMessage(
        role="assistant", content="",
        tool_calls=[_ToolCall(id=call_id, name=raw.get("name", tool.name),
                              arguments=raw.get("arguments", "{}"))],
    ))
    messages.append(ChatMessage(role="tool", content=tool_result_text,
                                tool_call_id=call_id, name=tool.name))

    llm, rm = await get_llm(db, tenant_id=ps.tenant_id)
    temp = 0.2

    # 工具集：与首次一致（只常驻核心工具；管理工具按需路由）
    perms_set: set[str] = set()
    tools: list = []
    dynamic_tools: dict = {}
    try:
        u = await db.get(User, ps.user_id) if ps.user_id else None
        perms_set = await get_user_permission_codes(db, u) if u else set()
        _cfg = {"builtin": {}}
        for t in _reg.all_builtin():
            _cfg["builtin"][t.name] = {"enabled": True}
        tools = await resolve_tools(
            db, tool_config=_cfg, skill_ids=[], tenant_id=ps.tenant_id, perms=perms_set,
            is_external=bool(getattr(ps, "is_external", False)),
        )
        dynamic_tools = resolve_admin_pool(
            perms=perms_set, is_external=bool(getattr(ps, "is_external", False)),
        )
    except Exception:  # noqa: BLE001
        logger.exception("resume_resolve_tools_failed")

    collected = ""
    collected_reasoning = ""
    usage: dict = {}

    async def _pending(t2, tc, args):
        import uuid as _uuid

        from app.models import AgentAction

        s = ""
        if hasattr(t2, "summarize"):
            try:
                s = t2.summarize(args)
            except Exception:  # noqa: BLE001
                s = f"将调用 {t2.name}"
        a = AgentAction(
            tenant_id=ps.tenant_id, conversation_id=conv.id, agent_id=None,
            user_id=ps.user_id, tool_name=t2.name, tool_kind="write", arguments=args,
            raw_tool_call={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
            summary=s, status="pending", idempotency_key=_uuid.uuid4().hex,
            expires_at=int(time.time() * 1000) + 10 * 60 * 1000,
        )
        db.add(a)
        await db.commit()
        return a

    async def _audit(tc, result, denied):
        try:
            from app.services.audit_service import record_audit

            record_audit(
                db, action="chat.tool_call", resource_type="tool", resource_id=tc.name,
                after={"arguments": tc.arguments[:1000], "is_error": result.is_error,
                       "latency_ms": result.latency_ms, "conversation_id": conv.id},
                result="failure" if (denied or result.is_error) else "success",
                error="permission_denied" if denied else None,
                tenant_id=ps.tenant_id, actor_id=ps.user_id, actor_type="user",
            )
        except Exception:  # noqa: BLE001
            pass

    suspended = False
    try:
        async for evt in run_react_loop(
            db=db, ps=ps, perms=perms_set, llm=llm, rm=rm, messages=messages,
            tools=tools, dynamic_tools=dynamic_tools, conversation_id=conv.id,
            temperature=temp, max_turns=6, allow_auto_write=allow_auto_write,
            on_audit=_audit, on_pending_action=(None if allow_auto_write else _pending),
        ):
            t = evt.get("type")
            if t == "delta":
                collected += evt.get("text", "")
                yield evt
            elif t == "reasoning":
                collected_reasoning += evt.get("text", "")
                yield evt
            elif t == "usage":
                usage.update(evt.get("usage") or {})
                yield evt
            elif t == "_suspended":
                suspended = True
                yield {"type": "done", "message_id": None, "suspended": True}
                return
            else:
                yield evt
    except Exception as e:  # noqa: BLE001
        logger.exception("resume_answer_failed")
        yield {"type": "error", "message": str(e)[:300]}

    if suspended:
        return

    from app.services.usage_service import normalize_usage

    norm = normalize_usage(usage)
    latency = int((time.time() - t0) * 1000)
    asst = Message(
        tenant_id=ps.tenant_id, conversation_id=conv.id, role="assistant",
        content=collected, reasoning=collected_reasoning or None,
        usage=norm, model=rm.model_name, latency_ms=latency,
        created_at=int(time.time() * 1000),
    )
    db.add(asst)
    conv.message_count = (conv.message_count or 0) + 1
    await db.commit()
    yield {"type": "usage", "usage": norm, "latency_ms": latency}
    yield {"type": "done", "message_id": asst.id}


async def regenerate_meta(db: AsyncSession, conversation_id: int, user_id: int) -> tuple[str, list[dict]]:
    """重新生成：删掉最后一条 assistant 消息，返回最后一条 user 消息的 (query, attachments)。"""
    from sqlalchemy import delete as sql_delete

    last_asst = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role == "assistant")
            .order_by(Message.id.desc())
        )
    ).scalars().first()
    if last_asst:
        await db.execute(sql_delete(Message).where(Message.id == last_asst.id))

    last_user = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role == "user")
            .order_by(Message.id.desc())
        )
    ).scalars().first()
    if last_user:
        # 删除该 user 消息（重新提问时 stream_answer 会再写一条）
        atts = last_user.attachments or []
        q = last_user.content
        await db.execute(sql_delete(Message).where(Message.id == last_user.id))
        await db.commit()
        return q, atts
    await db.commit()
    return "", []


async def complete_once(
    db: AsyncSession, *, ps: PrincipalSet, query: str, kb_ids: list[int] | None = None,
    top_k: int = 5, use_retrieval: bool = True
) -> tuple[str, dict, list[Citation]]:
    """非流式生成（供 OpenAI 兼容端点复用）。返回 (answer, usage, citations)。"""
    # 内容安全：输入侧检测
    g = guard_check(query)
    if g and g.blocked:
        raise ValidationError(f"输入被安全策略拦截（{g.risk_level}）: {g.summary()}")
    messages, _chunks, citations = await prepare(
        db, ps=ps, body_kb_ids=kb_ids or [], query=query, top_k=top_k, use_retrieval=use_retrieval
    )
    llm, rm = await get_llm(db, tenant_id=ps.tenant_id)
    res = await llm.chat(messages, model=rm.model_name, stream=False, temperature=0.2)
    return res.content, (res.usage or {}), citations
