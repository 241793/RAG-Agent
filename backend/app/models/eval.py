"""RAG 问答质量评估：测试集 → 批量跑问答 → LLM 裁判打分 → 报告。

设计：
- EvalDataset：一组测试问题（可绑定知识库）。EvalQuestion：单题（问题/期望答案/期望文档）。
- EvalRun：一次评测运行（进度/汇总分）。EvalResult：单题结果（答案/命中/忠实度/相关性）。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class EvalDataset(Base, IdMixin, TimestampMixin, TenantMixin):
    """评测数据集：一组测试问题，可绑定要评测的知识库。"""

    __tablename__ = "eval_dataset"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 评测时检索的知识库
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class EvalQuestion(Base, IdMixin, TimestampMixin, TenantMixin):
    """评测问题：问题 + 可选的标准答案/期望命中文档。"""

    __tablename__ = "eval_question"

    dataset_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 期望命中的 doc_id
    sort: Mapped[int] = mapped_column(Integer, default=0)


class EvalRun(Base, IdMixin, TimestampMixin, TenantMixin):
    """一次评测运行。"""

    __tablename__ = "eval_run"

    dataset_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    # 汇总：{faithfulness, relevance, hit_rate, avg_score, scored}
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_config_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ms
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class EvalResult(Base, IdMixin, TimestampMixin, TenantMixin):
    """单题评测结果。"""

    __tablename__ = "eval_result"

    run_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    question_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retrieved_doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hit_expected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 是否命中期望文档
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)  # 忠实度 1-5
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)  # 相关性 1-5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)  # 裁判评语
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
