"""知识库提示词放开 + use_retrieval 分支测试。

断言：
  - 新 SYSTEM_PROMPT 不含"只使用/无法回答"等硬约束，含"优先依据资料/用自身知识回答"
  - prepare(use_retrieval=False) 不调用 retrieve、无【参考资料】、system 为纯聊天提示词
  - prepare(use_retrieval=True) 走检索（回归）
  - ChatRequest.use_retrieval 默认 True、可设 False
"""
from __future__ import annotations

import asyncio
import types

import pytest

from app.core.db import AsyncSessionLocal, init_models
from app.schemas.chat import ChatRequest
from app.services import chat_service
from app.services.chat_service import PLAIN_SYSTEM_PROMPT, SYSTEM_PROMPT, prepare
from app.services.permission import PrincipalSet


def test_prompt_released():
    # 已放开"只使用知识库"，改为"区分标注"防幻觉策略
    assert "只使用" not in SYSTEM_PROMPT
    assert "明确区分" in SYSTEM_PROMPT
    assert "不在知识库中" in SYSTEM_PROMPT          # 自身知识须声明
    assert "不得编造或给自身知识标注编号" in SYSTEM_PROMPT  # 防伪造引用
    assert "不要因为资料缺失而拒答" not in SYSTEM_PROMPT     # 旧的"放绿"措辞已移除


def test_chat_request_use_retrieval():
    assert ChatRequest(message="hi").use_retrieval is True
    assert ChatRequest(message="hi", use_retrieval=False).use_retrieval is False


async def _run_prepare():
    await init_models()
    ps = PrincipalSet(user_id=1, tenant_id=1)
    async with AsyncSessionLocal() as db:
        # use_retrieval=False：应不调用 retrieve
        called = {"n": 0}
        orig = chat_service.retrieve

        async def _fake(*a, **k):
            called["n"] += 1
            raise AssertionError("use_retrieval=False 不应调用 retrieve")

        chat_service.retrieve = _fake
        try:
            msgs, chunks, cites = await prepare(
                db, ps=ps, body_kb_ids=[], query="你好", top_k=5, use_retrieval=False
            )
        finally:
            chat_service.retrieve = orig
        assert called["n"] == 0
        assert chunks == [] and cites == []
        assert msgs[0].role == "system" and msgs[0].content == PLAIN_SYSTEM_PROMPT
        # 最后一条是 user（中间可能插入平台能力段）
        last = msgs[-1]
        assert last.role == "user" and last.content == "你好"
        assert "【参考资料】" not in last.content

        # use_retrieval=True：应调用 retrieve（用 fake 保证不依赖真实检索）
        called2 = {"n": 0}

        async def _fake2(*a, **k):
            called2["n"] += 1
            return types.SimpleNamespace(chunks=[])

        chat_service.retrieve = _fake2
        try:
            msgs2, _, _ = await prepare(
                db, ps=ps, body_kb_ids=[], query="公司政策", top_k=5, use_retrieval=True
            )
        finally:
            chat_service.retrieve = orig
        assert called2["n"] == 1
        assert msgs2[0].content == SYSTEM_PROMPT
        assert "【参考资料】" in msgs2[-1].content

    print("OK chat_prompt")


def test_prepare_retrieval_branch():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_prepare())
    finally:
        loop.close()
        asyncio.set_event_loop(None)
