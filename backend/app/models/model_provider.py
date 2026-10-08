"""模型 Provider 与调用用量日志。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class ModelProvider(Base, IdMixin, TimestampMixin):
    """一个 provider = 一组凭证 + endpoint。tenant_id 为空表示平台级共享。"""

    __tablename__ = "model_provider"

    tenant_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="openai")  # openai/azure/anthropi/ollama/vllm/tei/custom
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 生产应加密
    extra_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timeout: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(16), default="active")
    health_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_check_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ModelConfig(Base, IdMixin, TimestampMixin, TenantMixin):
    """逻辑模型 = 用途 + 具体模型名。"""

    __tablename__ = "model_config"

    provider_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), default="chat")  # chat/embedding/rerank/vision/stt
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # 越小越优先（降级链）
    price_in_per_1k: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    price_out_per_1k: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")


class UsageLog(Base, IdMixin):
    __tablename__ = "usage_log"

    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    app_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    model_config_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    purpose: Mapped[str] = mapped_column(String(16), default="chat")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0)  # 毫秒时间戳
