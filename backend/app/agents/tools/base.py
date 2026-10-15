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
    # 群聊作用域：机器人在某群被 @ 时注入，房间作用域工具据此操作该群
    room_id: int | None = None
    emit: Callable[[dict], Awaitable[None]] | None = None
    config: dict = field(default_factory=dict)  # agent.tool_config[<tool_name>]
    # 本次调用是否处于「免确认/无人值守」模式（如用户开了免确认、定时任务）。
    # 工具据此判断：无人核验产出时（如录单），记录可直接落 confirmed 而非 draft。
    auto_write: bool = False


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

    def needs_confirm(self, args: dict) -> bool:
        """是否需要人工确认（按调用参数判定，默认跟随 auto_approve）。

        action 混合型工具可覆盖：只读 action（如 list_templates）免确认，
        写 action（如 extract+save）才确认。避免"看一眼模板"都要点审批。
        """
        return not self.auto_approve

    def summarize(self, args: dict) -> str:  # noqa: D401
        return f"将调用 {self.name}"

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return await self.execute(args, ctx)

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError


# ==================== 风险分级 ====================
# 敏感操作 = 会改数据/对外产生影响，且值得在审计日志里显著留痕的动作。
# 分级：0=只读；1=写但可逆/低风险；2=敏感（改数据/对外）；3=高危（删除/权限/密钥/对外发布）。
# 判定优先取工具显式声明的 risk_level，否则按 dangerous/kind 推断。
_RISK_DANGEROUS = 3
_RISK_WRITE = 2


def tool_risk_level(tool) -> int:
    """工具风险级别（0-3）。显式 risk_level 优先，否则由 dangerous/kind 推断。"""
    lvl = getattr(tool, "risk_level", None)
    if isinstance(lvl, int):
        return max(0, min(lvl, 3))
    if getattr(tool, "dangerous", False):
        return _RISK_DANGEROUS
    if getattr(tool, "kind", "read") == "write":
        return _RISK_WRITE
    return 0


def is_sensitive(tool) -> bool:
    """敏感操作：风险级别 >= 2（写数据/对外/高危）。用于审计显著标记与筛选。"""
    return tool_risk_level(tool) >= 2

