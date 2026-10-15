"""智能录单 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateField(BaseModel):
    name: str = Field(min_length=1)
    label: str = ""
    type: str = "text"  # text|number|date|phone|enum
    required: bool = False
    desc: str | None = None
    options: list | None = None


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    fields: list[TemplateField] = []
    instructions: str | None = None
    enabled: bool = True


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    fields: list[TemplateField] | None = None
    instructions: str | None = None
    enabled: bool | None = None


class TemplateOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    fields: list | None = None
    instructions: str | None = None
    enabled: bool

    model_config = {"from_attributes": True}


class ExtractIn(BaseModel):
    template_id: int
    text: str = ""            # 直接粘贴的文本
    doc_id: int | None = None  # 或从知识库文档取文本（与 text 二选一）
    source_type: str = "text"  # text|document|channel
    source_ref: str | None = None
    save: bool = True  # 是否保存为记录
    auto_confirm: bool = False  # 免确认模式：抽取直接落 confirmed（跳过人工核对）


class EntryUpdate(BaseModel):
    data: dict
    status: str | None = None


class EntryBatchIn(BaseModel):
    """批量操作记录。action: delete=删除 / confirm=确认 / unconfirm=退回草稿。"""
    action: str  # delete | confirm | unconfirm
    ids: list[int] = []
