"""人设模板：可复用的 system_prompt 素材（管理员可维护）。

用途：编辑智能体基座提示词、或添加「行为模式」时，可从模板一键套用后微调。
它只是**提示词素材库**，不建立与智能体的绑定关系 —— 套用即复制文本，
之后改模板不影响已套用的智能体。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class AgentPersonaTemplate(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "agent_persona_template"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_persona_tmpl_tenant_slug"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 幂等播种键：仅内置模板有值；自建模板为 NULL
    #（SQLite/PG/MySQL 均允许多个 NULL，故唯一约束不阻碍自建）
    slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 核心：预置的提示词正文
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="")  # 客服/研发/写作/通用
    icon: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 内置模板：可编辑、可复制，但禁止删除（避免列表被清空）
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
