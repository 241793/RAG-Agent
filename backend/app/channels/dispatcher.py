"""消息处理中枢：入站消息 → 身份解析 → 指令/AI → 回复。

RAG 模式：进程内直调 complete_once（chat_service.py:332）。
Agent 模式：复用 AgentRunner 流式收集全文。
"""
from __future__ import annotations

from app.channels.base import InboundMessage, OutboundMessage
from app.channels.commands import COMMANDS, CommandContext, is_command, parse_command
from app.core.logging import get_logger

logger = get_logger("channel")

# 转人工意图关键词（命中即建工单，不再由 AI 回答）
_HANDOFF_KEYWORDS = ("转人工", "人工客服", "找人工", "转客服", "真人", "人工服务", "人工")


def _wants_human(text: str | None) -> bool:
    """用户是否请求转人工。"""
    if not text:
        return False
    low = text.strip().lower()
    return any(k in low for k in _HANDOFF_KEYWORDS)


# 外部客户在渠道里可用的权限码（只读工具 + 问答检索）。
# 写/管理工具即使在此也不放行——resolve_tools(is_external=True) 只装 kind==read 工具。
_SERVICE_AGENT_PERMS = {"chat:use", "retrieval:query", "tool:invoke", "mcp:invoke"}


async def _channel_user_perms(db, user, bound_user=None) -> set[str]:
    """渠道用户权限码。

    - 已绑定内部账号：完全继承其真实权限（管理员得 *，普通同事得其角色码）。
    - 未绑定外部客户：service_agent 只读档。
    """
    from app.middleware.auth_dep import get_user_permission_codes

    if bound_user is not None:
        return await get_user_permission_codes(db, bound_user)
    if getattr(user, "user_type", "internal") == "external":
        return set(_SERVICE_AGENT_PERMS)
    return await get_user_permission_codes(db, user)


_LANG_INSTRUCTION = {
    "zh": "请用中文回答。", "en": "Please answer in English.", "ja": "日本語で答えてください。",
    "ko": "한국어로 답변해 주세요.", "es": "Responde en español.", "fr": "Réponds en français.",
    "de": "Antworte auf Deutsch.", "ru": "Отвечай по-русски.", "pt": "Responda em português.",
}


def _with_lang(query: str, lang: str | None) -> str:
    """给查询前置语言指令（多语言客服）。空则原样返回。"""
    inst = _LANG_INSTRUCTION.get(lang or "")
    return f"[{inst}]\n{query}" if inst else query


async def handle_inbound(
    adapter, channel, msg: InboundMessage, *, send: bool = True
) -> str:
    """处理一条入站消息，返回回复文本（可选是否真的发送）。"""
    from app.core.db import AsyncSessionLocal
    from app.services.channel_service import (
        ensure_conversation, principal_of, resolve_channel_user,
    )

    async with AsyncSessionLocal() as db:
        # 1) 身份解析（首次自动建档；可能已绑定内部账号）
        cu, user, bound_user = await resolve_channel_user(
            db, channel=channel, external_id=msg.external_user, display_name=msg.display_name
        )
        if user.status != "active":
            await db.commit()
            reply = "你的账号已被禁用，请联系管理员。"
            return await _reply(adapter, msg, reply, send)

        ps = principal_of(user, bound_user)
        prefix = channel.command_prefix or "/"

        # 2) 指令
        if is_command(msg.content, prefix):
            name, args = parse_command(msg.content, prefix)
            handler = COMMANDS.get(name)
            if not handler:
                reply = f"未知指令 /{name}。发送 /help 查看可用指令。"
            else:
                from app.services.retrieval_service import resolve_accessible_kbs

                kb_ids = await resolve_accessible_kbs(db, ps)
                from app.models import KnowledgeBase

                kbs = []
                if kb_ids:
                    from sqlalchemy import select

                    kbs = list((await db.execute(
                        select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
                    )).scalars().all())
                ctx = CommandContext(db=db, channel=channel, channel_user=cu, user=user, ps=ps, available_kbs=kbs,
                                     external_group=msg.external_group)
                try:
                    reply = await handler(ctx, args)
                except Exception as e:  # noqa: BLE001
                    logger.exception("command_failed", cmd=name)
                    reply = f"指令执行失败：{str(e)[:200]}"
            await db.commit()
            return await _reply(adapter, msg, reply, send)

        # 3) AI 回答
        conv = await ensure_conversation(db, cu=cu, channel=channel)
        kb_mode = getattr(channel, "kb_mode", "auto") or "auto"
        if cu.default_kb_ids is not None:
            # 用户指令级覆盖（/kb use/off）
            kb_ids = cu.default_kb_ids
            use_retrieval = bool(kb_ids)
        elif kb_mode == "off":
            kb_ids, use_retrieval = [], False
        elif kb_mode == "custom":
            kb_ids = channel.default_kb_ids or []
            use_retrieval = bool(kb_ids)
        else:  # auto：按渠道用户权限自动选全部有权库（与「智能问答」一致）
            from app.services.retrieval_service import resolve_accessible_kbs

            kb_ids = await resolve_accessible_kbs(db, ps)
            use_retrieval = bool(kb_ids)
        # 让渠道会话的知识库范围与用户选择同步（多轮上下文 + 落库）
        conv.kb_ids = kb_ids or []
        await db.commit()

        # 处理入站媒体：下载 → 落盘 → 附件 + 图片（给视觉模型）
        attachments, images = await _persist_attachments(db, ps, msg)

        # 客服：仅在「服务模式=support」时才处理转人工；qa 模式一律当普通问题
        support = (getattr(channel, "service_mode", "qa") or "qa") == "support"
        if support:
            from app.services.service_ticket_service import add_user_message, create_ticket, find_open_ticket

            # 已有进行中的工单 → 消息直接追加到工单（不再走 AI/重复建单）
            existing = await find_open_ticket(
                db, tenant_id=channel.tenant_id, channel_id=channel.id,
                external_user=msg.external_user, external_group=msg.external_group,
            )
            if existing is not None:
                await add_user_message(db, existing, msg.content)
                conv_id_for_reply = conv.id
                reply = f"你已有进行中的工单 #{existing.id}，已把你的消息转给客服，请稍候。"
                await db.commit()
                return await _reply(adapter, msg, reply, send, conversation_id=conv_id_for_reply)

            # 检测转人工意图 → 建工单，不再走 AI（后续由客服回复）
            if _wants_human(msg.content):
                tk = await create_ticket(
                    db, tenant_id=channel.tenant_id,
                    subject=(msg.content or "用户请求转人工")[:80], content=msg.content,
                    channel_id=channel.id, channel_kind=channel.kind,
                    external_user=msg.external_user, external_group=msg.external_group,
                    channel_user_id=cu.id, conversation_id=conv.id,
                )
                conv_id_for_reply = conv.id
                reply = f"已为你转接人工客服（工单 #{tk.id}），客服会尽快回复你。"
                await db.commit()
                return await _reply(adapter, msg, reply, send, conversation_id=conv_id_for_reply)

        # 多语言：用户 /lang 设置 > 自动检测 > 渠道默认
        from app.channels.commands import detect_lang

        lang = cu.lang or detect_lang(msg.content) or getattr(channel, "default_lang", None) or None

        try:
            knowledge_media: list[dict] = []
            if cu.agent_id:
                reply = await _run_agent(cu.agent_id, conv.id, user, msg.content, images=images, lang=lang,
                                         bound_user=bound_user)
            else:
                # 绑定内部账号 → 允许工具循环（读+写，写操作直接执行）；
                # 未绑定的外部客户 → 纯问答（不装工具）。
                reply, knowledge_media = await _run_rag(ps, conv.id, msg.content, use_retrieval,
                                       attachments=attachments, images=images, lang=lang,
                                       use_tools=bound_user is not None)
        except Exception as e:  # noqa: BLE001
            logger.exception("channel_ai_failed", channel=channel.kind)
            reply = f"处理失败：{str(e)[:200]}"
            knowledge_media = []
        conv_id_for_reply = conv.id

        # 渠道会话：客户新消息 → 按会话提醒开关通知客服
        try:
            from app.services.service_ticket_service import notify_conversation_reply

            await notify_conversation_reply(db, conv, msg.content)
        except Exception:  # noqa: BLE001
            logger.exception("conversation_reply_notify_failed", conversation_id=conv.id)

    return await _reply(adapter, msg, reply, send, conversation_id=conv_id_for_reply,
                        extra_media=knowledge_media)


async def _persist_attachments(db, ps, msg: InboundMessage) -> tuple[list[dict], list[dict]]:
    """下载入站媒体 → 存 storage + Artifact → 返回 (附件dict列表, images列表)。"""
    from app.channels import media as medi
    from app.ingest.storage import get_storage
    from app.models import Artifact

    if not msg.attachments:
        return [], []
    storage = get_storage()
    out: list[dict] = []
    images: list[dict] = []
    for att in msg.attachments:
        data, ext = await medi.download_media(att)
        if not data:
            logger.warning("channel_media_download_failed", channel=msg.channel,
                           name=att.get("name"))
            continue
        name = att.get("name") or f"media.{ext or 'bin'}"
        try:
            file_key, _hash = storage.save(tenant_id=ps.tenant_id, filename=name, data=data)
        except Exception:  # noqa: BLE001
            logger.exception("channel_media_save_failed")
            continue
        mime = medi.mime_of(name, ext)
        # 统一文件管理记录
        try:
            db.add(Artifact(
                tenant_id=ps.tenant_id, user_id=ps.user_id, file_name=name,
                file_key=file_key, file_ext=ext, mime=mime, size=len(data), source="channel",
            ))
            await db.flush()
        except Exception:  # noqa: BLE001
            logger.warning("channel_artifact_record_failed", name=name)
        att_rec = {
            "type": att.get("type") or "file", "file_key": file_key, "name": name,
            "mime": mime, "size": len(data), "url": f"/api/v1/chat/attachments/{file_key}",
        }
        out.append(att_rec)
        if (att.get("type") == "image"):
            import base64

            b64 = base64.b64encode(data).decode()
            images.append({"url": f"data:{mime};base64,{b64}"})
    if out:
        await db.commit()
    return out, images


async def _run_rag(ps, conversation_id: int, query: str, use_retrieval: bool,
                   attachments: list[dict] | None = None, images: list[dict] | None = None,
                   lang: str | None = None, use_tools: bool = False) -> tuple[str, list[dict]]:
    """走 stream_answer：落库用户/助手消息 + 带多轮上下文（与「智能问答」一致）。

    返回 (回答文本, 命中知识条目的配套媒体列表)。命中图文条目时，把其附件读成 bytes，
    由调用方随回复一并发给渠道用户。
    """
    from app.core.db import AsyncSessionLocal
    from app.models import Conversation
    from app.services.chat_service import stream_answer

    q = _with_lang(query, lang)
    async with AsyncSessionLocal() as db:
        conv = await db.get(Conversation, conversation_id)
        if not conv:
            return "会话不存在。", []
        collected = ""
        citations = []
        async for evt in stream_answer(
            db, ps=ps, conversation=conv, query=q, top_k=5,
            use_retrieval=use_retrieval, attachments=attachments or None,
            images=images or None, use_tools=use_tools, allow_auto_write=use_tools,
        ):
            t = evt.get("type")
            if t == "delta":
                collected += evt.get("text", "")
            elif t == "citations":
                citations = evt.get("citations") or []
            elif t == "error":
                collected += f"\n[错误] {evt.get('message')}"
    answer = collected or "（无回复）"
    if citations:
        srcs = "、".join((c.doc_title if hasattr(c, "doc_title") else c.get("doc_title")) or "文档"
                        for c in citations[:3])
        answer += f"\n\n（参考：{srcs}）"
    media = _collect_citation_media(citations)
    return answer, media


def _collect_citation_media(citations: list, limit: int = 5) -> list[dict]:
    """把命中的图文条目附件读成出站媒体（去重、限量，避免刷屏）。"""
    from app.ingest.storage import get_storage

    media: list[dict] = []
    seen: set[str] = set()
    try:
        storage = get_storage()
        for c in citations:
            atts = c.get("attachments") if isinstance(c, dict) else getattr(c, "attachments", None)
            for a in (atts or []):
                if not isinstance(a, dict):
                    continue
                key = a.get("file_key")
                if not key or key in seen:
                    continue
                seen.add(key)
                try:
                    data = storage.read(key)
                except Exception:  # noqa: BLE001
                    continue
                mime = a.get("mime") or ""
                media.append({
                    "type": "image" if str(mime).startswith("image/") else "file",
                    "name": a.get("name") or "file", "data": data,
                })
                if len(media) >= limit:
                    return media
    except Exception:  # noqa: BLE001
        logger.exception("collect_citation_media_failed")
    return media


async def _run_agent(agent_id: int, conversation_id: int, user, query: str,
                     images: list[dict] | None = None, lang: str | None = None,
                     bound_user=None) -> str:
    from app.core.db import AsyncSessionLocal
    from app.models import Agent, Conversation
    from app.agents.runner import AgentRunner
    from app.services.channel_service import principal_of
    from app.services.context_service import load_context

    query = _with_lang(query, lang)
    async with AsyncSessionLocal() as db:
        agent = await db.get(Agent, agent_id)
        conv = await db.get(Conversation, conversation_id)
        if not agent or not conv:
            return "智能体或会话不存在。"
        ps = principal_of(user, bound_user)
        summary, history = await load_context(db, conv)
        # 权限码：绑定内部账号 → 真实权限；外部客户 → service_agent 只读档。
        perms = await _channel_user_perms(db, user, bound_user)
        runner = AgentRunner(db, agent=agent, ps=ps, conversation=conv, history=history, summary=summary,
                             perms=perms, images=images or None,
                             allow_auto_write=bound_user is not None)
        text = ""
        async for evt in runner.run(query):
            if evt.get("type") == "delta":
                text += evt.get("text", "")
            elif evt.get("type") == "error":
                text += f"\n[错误] {evt.get('message')}"
        return text or "（无回复）"


async def _reply(adapter, msg: InboundMessage, text: str, send: bool,
                 conversation_id: int | None = None,
                 extra_media: list[dict] | None = None) -> str:
    """把回复发回渠道（群聊回群，私聊回人）。附带本轮 AI 生成的文件 + 命中知识条目的配套文件。"""
    if send and adapter is not None:
        media: list[dict] = []
        if conversation_id:
            media = await _collect_reply_media(conversation_id)
        if extra_media:
            # 合并命中条目的附件，按 file_key/name 去重
            seen = {(m.get("name"), len(m.get("data") or b"")) for m in media}
            for m in extra_media:
                k = (m.get("name"), len(m.get("data") or b""))
                if k not in seen:
                    seen.add(k)
                    media.append(m)
        out = OutboundMessage(
            content=text,
            group_id=msg.external_group if msg.is_group else None,
            user_id=None if msg.is_group else msg.external_user,
            reply_to=msg.message_id,
            account=msg.account,
            media=media,
        )
        try:
            await adapter.send_message(out)
        except Exception:  # noqa: BLE001
            logger.exception("channel_send_failed", channel=msg.channel)
    return text


async def _collect_reply_media(conversation_id: int) -> list[dict]:
    """取该会话本轮 AI 生成的文件（近 2 分钟内），转成出站媒体。"""
    from sqlalchemy import select

    from app.core.db import AsyncSessionLocal
    from app.ingest.storage import get_storage
    from app.models import Artifact, Message

    media: list[dict] = []
    try:
        async with AsyncSessionLocal() as db:
            # 该会话最新消息 id
            last = (await db.execute(
                select(Message.id).where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc()).limit(1)
            )).scalar_one_or_none()
            if not last:
                return []
            rows = (await db.execute(
                select(Artifact).where(Artifact.message_id == last)
            )).scalars().all()
            storage = get_storage()
            for a in rows:
                try:
                    data = storage.read(a.file_key)
                except Exception:  # noqa: BLE001
                    continue
                mime = a.mime or ""
                atype = "image" if mime.startswith("image/") else "file"
                media.append({"type": atype, "name": a.file_name, "data": data})
    except Exception:  # noqa: BLE001
        logger.warning("collect_reply_media_failed", conversation_id=conversation_id)
    return media
