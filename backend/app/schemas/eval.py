"""RAG 问答质量评估 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    kb_ids: list[int] | None = None


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    kb_ids: list[int] | None = None


class DatasetOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    kb_ids: list | None = None
    question_count: int | None = None

    model_config = {"from_attributes": True}


class QuestionIn(BaseModel):
    question: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_doc_ids: list[int] | None = None


class QuestionUpdate(BaseModel):
    question: str | None = None
    expected_answer: str | None = None
    expected_doc_ids: list[int] | None = None


class QuestionOut(BaseModel):
    id: int
    dataset_id: int
    question: str
    expected_answer: str | None = None
    expected_doc_ids: list | None = None
    sort: int = 0

    model_config = {"from_attributes": True}


class RunCreate(BaseModel):
    model_config_id: int | None = None
    top_k: int = 5


class RunOut(BaseModel):
    id: int
    dataset_id: int
    status: str
    progress: int = 0
    total: int = 0
    summary: dict | None = None
    error: str | None = None
    started_at: int | None = None
    finished_at: int | None = None

    model_config = {"from_attributes": True}


class ResultOut(BaseModel):
    id: int
    question: str
    answer: str | None = None
    hit_expected: bool | None = None
    faithfulness: float | None = None
    relevance: float | None = None
    comment: str | None = None
    latency_ms: int | None = None
    error: str | None = None

    model_config = {"from_attributes": True}
