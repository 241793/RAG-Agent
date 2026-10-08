"""RAG 问答质量评估接口：数据集/问题 CRUD + 运行评测 + 查看报告 + 导出。

权限码 eval:read / eval:manage。
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import EvalDataset, EvalQuestion, EvalResult, EvalRun, User
from app.schemas.eval import (
    DatasetCreate,
    DatasetOut,
    DatasetUpdate,
    QuestionIn,
    QuestionOut,
    QuestionUpdate,
    ResultOut,
    RunCreate,
    RunOut,
)
from app.services.audit_service import audited

router = APIRouter(prefix="/eval", tags=["eval"])


async def _get_dataset(db: AsyncSession, ds_id: int, tenant_id: int) -> EvalDataset:
    ds = await db.get(EvalDataset, ds_id)
    if not ds or ds.tenant_id != tenant_id:
        raise NotFoundError("数据集不存在")
    return ds


# ==================== 数据集 ====================
@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(
    user: User = Depends(require_permission("eval:read")),
    db: AsyncSession = Depends(get_db),
) -> list[DatasetOut]:
    rows = (await db.execute(
        select(EvalDataset).where(EvalDataset.tenant_id == user.tenant_id).order_by(EvalDataset.id.desc())
    )).scalars().all()
    # 带问题数
    out: list[DatasetOut] = []
    for ds in rows:
        cnt = (await db.execute(
            select(func.count()).select_from(EvalQuestion).where(EvalQuestion.dataset_id == ds.id)
        )).scalar_one()
        o = DatasetOut.model_validate(ds)
        o.question_count = int(cnt)
        out.append(o)
    return out


@router.post("/datasets", response_model=DatasetOut)
@audited("eval.dataset.create", "eval_dataset")
async def create_dataset(
    body: DatasetCreate,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    ds = EvalDataset(
        tenant_id=user.tenant_id, name=body.name, description=body.description,
        kb_ids=body.kb_ids, created_by=user.id,
    )
    db.add(ds)
    await db.flush()
    o = DatasetOut.model_validate(ds)
    o.question_count = 0
    return o


@router.patch("/datasets/{ds_id}", response_model=DatasetOut)
@audited("eval.dataset.update", "eval_dataset", id_arg="ds_id")
async def update_dataset(
    ds_id: int,
    body: DatasetUpdate,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    ds = await _get_dataset(db, ds_id, user.tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ds, k, v)
    await db.flush()
    return DatasetOut.model_validate(ds)


@router.delete("/datasets/{ds_id}")
@audited("eval.dataset.delete", "eval_dataset", id_arg="ds_id")
async def delete_dataset(
    ds_id: int,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import delete as _del

    ds = await _get_dataset(db, ds_id, user.tenant_id)
    await db.execute(_del(EvalQuestion).where(EvalQuestion.dataset_id == ds_id))
    await db.delete(ds)
    await db.flush()
    return {"message": "已删除"}


# ==================== 问题 ====================
@router.get("/datasets/{ds_id}/questions", response_model=list[QuestionOut])
async def list_questions(
    ds_id: int,
    user: User = Depends(require_permission("eval:read")),
    db: AsyncSession = Depends(get_db),
) -> list[QuestionOut]:
    await _get_dataset(db, ds_id, user.tenant_id)
    rows = (await db.execute(
        select(EvalQuestion).where(EvalQuestion.dataset_id == ds_id).order_by(EvalQuestion.sort, EvalQuestion.id)
    )).scalars().all()
    return [QuestionOut.model_validate(q) for q in rows]


@router.post("/datasets/{ds_id}/questions", response_model=QuestionOut)
@audited("eval.question.create", "eval_question", id_arg="ds_id")
async def add_question(
    ds_id: int,
    body: QuestionIn,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> QuestionOut:
    await _get_dataset(db, ds_id, user.tenant_id)
    q = EvalQuestion(
        tenant_id=user.tenant_id, dataset_id=ds_id, question=body.question,
        expected_answer=body.expected_answer, expected_doc_ids=body.expected_doc_ids,
    )
    db.add(q)
    await db.flush()
    return QuestionOut.model_validate(q)


@router.patch("/questions/{q_id}", response_model=QuestionOut)
@audited("eval.question.update", "eval_question", id_arg="q_id")
async def update_question(
    q_id: int,
    body: QuestionUpdate,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> QuestionOut:
    q = await db.get(EvalQuestion, q_id)
    if not q or q.tenant_id != user.tenant_id:
        raise NotFoundError("问题不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(q, k, v)
    await db.flush()
    return QuestionOut.model_validate(q)


@router.delete("/questions/{q_id}")
@audited("eval.question.delete", "eval_question", id_arg="q_id")
async def delete_question(
    q_id: int,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = await db.get(EvalQuestion, q_id)
    if not q or q.tenant_id != user.tenant_id:
        raise NotFoundError("问题不存在")
    await db.delete(q)
    await db.flush()
    return {"message": "已删除"}


# ==================== 运行评测 ====================
@router.post("/datasets/{ds_id}/run", response_model=RunOut)
@audited("eval.run", "eval_dataset", id_arg="ds_id")
async def start_run(
    ds_id: int,
    body: RunCreate,
    user: User = Depends(require_permission("eval:manage")),
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    ds = await _get_dataset(db, ds_id, user.tenant_id)
    cnt = (await db.execute(
        select(func.count()).select_from(EvalQuestion).where(EvalQuestion.dataset_id == ds.id)
    )).scalar_one()
    if not cnt:
        raise ValidationError("数据集没有问题，无法评测")
    run = EvalRun(
        tenant_id=user.tenant_id, dataset_id=ds.id, status="pending",
        total=int(cnt), model_config_id=body.model_config_id, created_by=user.id,
    )
    db.add(run)
    await db.flush()
    run_id = run.id
    await db.commit()

    # 入队（提交后，独立 session 执行）
    from app.tasks.eval_tasks import enqueue_eval

    await enqueue_eval(run_id, body.top_k)
    return RunOut.model_validate(run)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: int,
    user: User = Depends(require_permission("eval:read")),
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    run = await db.get(EvalRun, run_id)
    if not run or run.tenant_id != user.tenant_id:
        raise NotFoundError("评测运行不存在")
    return RunOut.model_validate(run)


@router.get("/runs/{run_id}/results", response_model=list[ResultOut])
async def get_run_results(
    run_id: int,
    user: User = Depends(require_permission("eval:read")),
    db: AsyncSession = Depends(get_db),
) -> list[ResultOut]:
    run = await db.get(EvalRun, run_id)
    if not run or run.tenant_id != user.tenant_id:
        raise NotFoundError("评测运行不存在")
    rows = (await db.execute(
        select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.id)
    )).scalars().all()
    return [ResultOut.model_validate(r) for r in rows]


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: int,
    user: User = Depends(require_permission("eval:read")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """导出评测结果为 CSV。"""
    run = await db.get(EvalRun, run_id)
    if not run or run.tenant_id != user.tenant_id:
        raise NotFoundError("评测运行不存在")
    rows = (await db.execute(
        select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.id)
    )).scalars().all()

    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["问题", "回答", "命中期望文档", "忠实度", "相关性", "耗时ms", "评语", "错误"])
    for r in rows:
        w.writerow([
            r.question or "", (r.answer or "").replace("\n", " "),
            "" if r.hit_expected is None else ("是" if r.hit_expected else "否"),
            "" if r.faithfulness is None else r.faithfulness,
            "" if r.relevance is None else r.relevance,
            r.latency_ms or "", (r.comment or "").replace("\n", " "), r.error or "",
        ])
    data = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([data]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="eval_run_{run_id}.csv"'},
    )
