"""离线 Agent 测试驱动（无需网络，用于验证 ReAct 工具循环）。

行为：若消息里还没有工具结果 → 首轮发出一次 knowledge_retrieval 工具调用；
已有工具结果 → 返回基于工具结果的终答。用于离线端到端验证 Agent 引擎。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import AsyncIterator

from app.providers.base import (
    ChatChunk,
    ChatMessage,
    ChatResult,
    ProviderHealth,
    ToolCall,
    ToolCallDelta,
)


class LocalAgentDriver:
    def __init__(self, *, tool_name: str = "knowledge_retrieval") -> None:
        self.tool_name = tool_name

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        stream: bool = False,
        tools: list[dict] | None = None,
        **kw,
    ):
        has_tool_result = any(m.role == "tool" for m in messages)
        # 找出最后一条 user 消息作为检索 query
        query = ""
        for m in reversed(messages):
            if m.role == "user":
                query = m.content
                break
        tool_ctx = "\n".join(m.content for m in messages if m.role == "tool")

        if not has_tool_result and tools:
            # 首轮：发起工具调用
            call = ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=self.tool_name,
                arguments=json.dumps({"query": query[:100]}, ensure_ascii=False),
            )
            if stream:
                async def _gen():
                    yield ChatChunk(
                        tool_calls=[ToolCallDelta(index=0, id=call.id, name=call.name, arguments_delta="")]
                    )
                    # 参数分片
                    args = call.arguments
                    for i in range(0, len(args), 8):
                        yield ChatChunk(
                            tool_calls=[ToolCallDelta(index=0, arguments_delta=args[i : i + 8])]
                        )
                    yield ChatChunk(
                        usage={"prompt_tokens": 10, "completion_tokens": 5}, finish=True
                    )

                return _gen()
            return ChatResult(
                content="", model="local-agent", finish_reason="tool_calls", tool_calls=[call]
            )

        # 终答：基于工具结果
        answer = (
            "【离线 Agent 回复】\n"
            "我已根据知识库检索到以下内容作答：\n\n"
            + (tool_ctx[:800] if tool_ctx else "（无工具结果）")
        )
        if stream:
            async def _gen2():
                for ch in answer:
                    yield ChatChunk(delta=ch)
                yield ChatChunk(usage={"prompt_tokens": 20, "completion_tokens": 30}, finish=True)

            return _gen2()
        return ChatResult(content=answer, model="local-agent")

    async def health(self, **kw) -> ProviderHealth:
        return ProviderHealth(ok=True, message="离线 Agent 驱动就绪", latency_ms=0)
