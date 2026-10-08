"""工具系统基础：Tool 协议、工具上下文与结果。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.permission import PrincipalSet


@dataclass
class ToolContext:
    """工具执行上下文。ps 是权限感知检索的关键，所有检索类工具必须用它。"""

    db: AsyncSession
    ps: PrincipalSet
    tenant_id: int
    user_id: int
    conversation_id: int | None = None
    agent_id: int | None = None
    run_id: int | None = None
    emit: Callable[[dict], Awaitable[None]] | None = None
    config: dict = field(default_factory=dict)  # agent.tool_config[<tool_name>]


@dataclass
class ToolResult:
    content: str  # 回灌给 LLM 的文本
    data: dict | None = None  # 结构化输出（前端展示）
    citations: list | None = None  # 检索类工具产出
    is_error: bool = False
    latency_ms: int | None = None  # 执行耗时（由 react 循环回填，供审计统计）


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    parameters: dict  # JSON Schema
    # 调用该工具所需的权限码；None = 公开。未声明者按"需显式授权"处理（默认不暴露）。
    required_permission: str | None
    # 工具类别：read=只读（直接执行）；write=写操作（可触发 HITL 确认）。
    kind: str

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult: ...


class WriteToolMixin:
    """write 类工具基类：run 转发 execute；summarize 供确认卡片展示影响。

    子类需实现 `execute()`，可选覆盖 `summarize()`。
    """

    kind = "write"
    dangerous = False  # True=高危（删除类），UI 提示用
    # True=高频工具，免人工确认（直接执行）；仍保留 kind="write" 以拦截外部客户。
    # 仅用于确知副作用可控/频率高的工具（如 http_request）。
    auto_approve = False

    def summarize(self, args: dict) -> str:  # noqa: D401
        return f"将调用 {self.name}"

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return await self.execute(args, ctx)

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError
