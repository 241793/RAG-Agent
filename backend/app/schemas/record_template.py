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
    text: str
    source_type: str = "text"  # text|document|channel
    source_ref: str | None = None
    save: bool = True  # 是否保存为记录


class EntryOut(BaseModel):
    id: int
    template_id: int
    data: dict | None = None
    source_type: str
    source_ref: str | None = None
    status: str

    model_config = {"from_attributes": True}


class EntryUpdate(BaseModel):
    data: dict
    status: str | None = None
