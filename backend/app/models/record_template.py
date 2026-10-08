"""智能录单：用 LLM 从自然语言/文档中抽取结构化字段，生成业务记录（可导出 Excel/CSV）。

场景：客服把通话记录/微信聊天发来 → AI 按「录入模板」抽取订单/客户/工单字段 → 一键导出台账。

设计：
- RecordTemplate：定义字段（name/label/type/required/desc），一套模板录一张表。
- 抽取：把模板 + 文本给 LLM，要求返回 JSON 数组（一单一条）；解析失败回退。
- 结果落 RecordEntry（JSON 行），可导出 Excel/CSV/Markdown。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class RecordTemplate(Base, IdMixin, TimestampMixin, TenantMixin):
    """录单模板：定义要从文本中抽取哪些字段。"""

    __tablename__ = "record_template"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 字段定义：[{name, label, type(text|number|date|phone|enum), required, desc, options}]
    fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 抽取的额外提示（业务背景）
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class RecordEntry(Base, IdMixin, TimestampMixin, TenantMixin):
    """一条录单记录（抽取结果，JSON 行）。"""

    __tablename__ = "record_entry"

    template_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    # 抽取出的字段值 {field_name: value}
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 来源：渠道消息/知识库文档/手动文本
    source_type: Mapped[str] = mapped_column(String(16), default="text")  # text|document|channel
    source_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 原始文本（追溯）
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|confirmed
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
