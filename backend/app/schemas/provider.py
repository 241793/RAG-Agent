"""模型 Provider DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderCreate(BaseModel):
    name: str
    kind: str = "openai"  # openai/azure/anthropi/ollama/vllm/tei/custom
    base_url: str
    api_key: str | None = None
    extra_headers: dict | None = None
    timeout: int = 60
    max_retries: int = 2


class ProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout: int | None = None
    status: str | None = None


class ProviderOut(BaseModel):
    id: int
    name: str
    kind: str
    base_url: str
    api_key_set: bool = False
    status: str
    health_status: str | None = None
    last_check_at: int | None = None
    timeout: int | None = None
    extra_headers: dict | None = None

    model_config = {"from_attributes": True}


class ModelConfigCreate(BaseModel):
    provider_id: int
    purpose: str = "chat"  # chat/embedding/rerank
    model_name: str
    display_name: str = ""
    params: dict | None = None
    embedding_dim: int | None = None
    is_default: bool = False
    priority: int = 100


class ModelConfigOut(BaseModel):
    id: int
    provider_id: int
    purpose: str
    model_name: str
    display_name: str
    embedding_dim: int | None = None
    is_default: bool
    priority: int
    status: str

    model_config = {"from_attributes": True}


class ProviderTestRequest(BaseModel):
    purpose: str = "chat"
    model_name: str | None = None
    text: str | None = None


class ProviderTestResult(BaseModel):
    ok: bool
    latency_ms: int = 0
    message: str = ""
    detail: str | None = None
