"""智能体（Agent）平台数据模型。

一张 Agent 表通过 type 区分「工具循环 Agent」与「工作流 Agent」。
Skill 表达两种用途（kind 区分）；Tool 存自定义工具；AgentMode 存行为模式。
Workflow/WorkflowRun/NodeRun 存工作流图与运行轨迹。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Agent(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_agent_tenant_slug"),)

    owner_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(16), default="agent")  # agent | workflow
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    model_config_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 默认检索范围
    skill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 引用的技能
    tool_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # max_turns/temperature 等
    default_mode_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|published|disabled
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # private|tenant
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMode(Base, IdMixin, TimestampMixin, TenantMixin):
    """行为模式：同一智能体的多套行为（提示词 + 工具 + 参数）。"""

    __tablename__ = "agent_mode"

    agent_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, default="")  # 叠加在 agent 基座之后
    skill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 非空则覆盖
    tool_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 深合并覆盖
    kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Skill(Base, IdMixin, TimestampMixin, TenantMixin):
    """技能 = 能力包(prompt_pack) 或 工具(tool)。"""

    __tablename__ = "skill"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_skill_tenant_slug"),)

    owner_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="prompt_pack")  # prompt_pack | tool | collection

    # 能力包用
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    params_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 带出的工具
    kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_config_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 工具用
    tool_def: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 技能包来源
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | package
    body_md: Mapped[str | None] = mapped_column(Text, nullable=True)  # 技能包 SKILL.md 正文
    package_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 技能集合（多技能仓库）：父技能 kind=collection，子技能 parent_id 指向父
    parent_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    collection_subpath: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 子技能在仓库内的目录

    status: Mapped[str] = mapped_column(String(16), default="active")
    visibility: Mapped[str] = mapped_column(String(16), default="private")


class SkillPackage(Base, IdMixin, TimestampMixin, TenantMixin):
    """技能包：从本地 zip / URL / GitHub 导入的技能包。"""

    __tablename__ = "skill_package"

    skill_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    source_type: Mapped[str] = mapped_column(String(16), default="zip")  # zip|url|github
    source_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pack_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 解压目录(file_key)
    manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # SKILL.md frontmatter
    files: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{path,size}]
    entry_scripts: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 可用脚本
    scripts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 脚本是否允许执行
    import_status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|failed
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Tool(Base, IdMixin, TimestampMixin, TenantMixin):
    """自定义工具持久化（内置工具由代码注册，不入库）。"""

    __tablename__ = "tool"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tool_tenant_name"),)

    owner_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="http")  # http | builtin
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")


class Workflow(Base, IdMixin, TimestampMixin, TenantMixin):
    """工作流图（属于 workflow 型 Agent）。"""

    __tablename__ = "workflow"

    agent_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="")
    graph: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {nodes:[],edges:[]}
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRun(Base, IdMixin, TenantMixin):
    __tablename__ = "workflow_run"

    workflow_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    agent_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|failed|canceled|waiting
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    graph_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 审批暂停时的 {variables}
    pending_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 等待审批的节点
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class NodeRun(Base, IdMixin, TenantMixin):
    __tablename__ = "node_run"

    run_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|success|failed|skipped|waiting
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AgentAction(Base, IdMixin, TimestampMixin, TenantMixin):
    """AI 工具写操作的待确认动作（HITL）：AI 发起 → 人工确认 → 执行。

    write 类工具不直接执行，先落此表 status=pending，前端弹确认卡片；
    确认端点用 CAS（WHERE status='pending'）防重放，确认者需具备该工具权限。
    """

    __tablename__ = "agent_action"

    conversation_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    agent_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)  # 发起者
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_kind: Mapped[str] = mapped_column(String(16), default="write")
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_tool_call: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # LLM 原始 tool_call（续跑必需）
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 人类可读影响摘要
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected|executed|expired|failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    executed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AgentVersion(Base, IdMixin, TimestampMixin, TenantMixin):
    """智能体版本快照（可回滚）。"""

    __tablename__ = "agent_version"

    agent_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
