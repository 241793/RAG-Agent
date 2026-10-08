"""OpenAI 兼容端点：让内部系统用现成 OpenAI SDK 接入本平台知识库。

仅非流式；鉴权用 X-API-Key；KB 范围受 key.kb_ids 限制。
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AuthError, PermissionDeniedError
from app.middleware.auth_dep import ApiKeyAuth, get_apikey_auth

router = APIRouter(prefix="/v1", tags=["openai-compat"])


@router.get("/models")
async def list_models(auth: ApiKeyAuth = Depends(get_apikey_auth)) -> dict:
    return {
        "object": "list",
        "data": [{"id": "rag-knowledge-base", "object": "model", "owned_by": "rag-platform"}],
    }


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    auth: ApiKeyAuth = Depends(get_apikey_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not auth.has_scope("chat:use"):
        raise PermissionDeniedError("API Key 缺少 chat:use 权限")

    body = await request.json()
    messages = body.get("messages") or []
    # 取最后一条 user 消息作为查询
    query = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            query = m.get("content") or ""
            break
    if not query:
        raise AuthError("缺少 user 消息")

    # KB 范围：请求指定与 key 限制取交集
    req_kbs = body.get("kb_ids")
    force = auth.kb_ids
    if force is not None:
        kb_ids = [k for k in (req_kbs or force) if k in set(force)]
    else:
        kb_ids = req_kbs

    from app.services.chat_service import complete_once

    t0 = time.time()
    answer, usage, citations = await complete_once(
        db, ps=auth.ps, query=query, kb_ids=kb_ids, top_k=int(body.get("top_k") or 5)
    )

    model = body.get("model") or "rag-knowledge-base"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        },
        # 平台扩展：引用来源
        "citations": [
            {"doc_id": c.doc_id, "doc_title": c.doc_title, "page": c.page, "score": c.score}
            for c in citations
        ],
    }
