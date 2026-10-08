"""RAG 问答质量评估服务：逐题跑问答 → 客观命中 + LLM 裁判打分 → 汇总。

复用：
- chat_service.complete_once（非流式 RAG 问答，不落库）
- providers.registry.get_llm / usage_service.normalize_usage
"""
from __future__ import annotations

import json
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("eval")

JUDGE_SYSTEM = (
    "你是 RAG 评测裁判。给定【问题】【检索到的资料】【模型回答】【参考答案(可选)】，"
    "对回答打分，只输出 JSON，不要任何多余文字：\n"
    '{"faithfulness": <1-5>, "relevance": <1-5>, "comment": "<简短评语>"}\n'
    "faithfulness：回答中的事实是否都能被【检索资料】支持（有编造则给低分）。\n"
    "relevance：回答是否切题、是否直接回答了问题。\n"
    "1=完全不行，3=一般，5=很好。"
)


def _parse_judge_json(text: str) -> dict:
    """从裁判输出里解析 JSON（容错：剥离 ``` 包裹、抓第一个 {...}）。"""
    if not text:
        return {}
    t = text.strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


async def judge_answer(
    db: AsyncSession, *, tenant_id: int, question: str, answer: str,
    contexts: list[str], expected_answer: str | None = None,
) -> dict:
    """调 LLM 给一条回答打分，返回 {faithfulness, relevance, comment}。失败返回 {}。"""
    from app.providers.base import ChatMessage
    from app.providers.registry import get_llm

    ctx_text = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(contexts)) or "（无检索资料）"
    user = (
        f"【问题】\n{question}\n\n【检索到的资料】\n{ctx_text}\n\n"
        f"【模型回答】\n{answer}\n\n"
    )
    if expected_answer:
        user += f"【参考答案】\n{expected_answer}\n\n"
    user += "请输出 JSON 打分。"
    try:
        llm, rm = await get_llm(db, tenant_id=tenant_id)
        res = await llm.chat(
            [ChatMessage(role="system", content=JUDGE_SYSTEM),
             ChatMessage(role="user", content=user)],
            model=rm.model_name, stream=False, temperature=0.0,
        )
    except Exception:  # noqa: BLE001
        logger.exception("judge_failed")
        return {}
    data = _parse_judge_json(getattr(res, "content", "") or "")
    out: dict = {}
    for k in ("faithfulness", "relevance"):
        v = data.get(k)
        if isinstance(v, (int, float)):
            out[k] = float(v)
    if data.get("comment"):
        out["comment"] = str(data["comment"])[:500]
    return out


async def run_eval(db: AsyncSession, *, run_id: int, top_k: int = 5) -> None:
    """执行一次评测（后台任务调用）。逐题：问答 → 客观命中 → LLM 裁判 → 写 EvalResult。"""
    from app.models import EvalDataset, EvalQuestion, EvalResult, EvalRun, UsageLog
    from app.services.chat_service import complete_once
    from app.services.permission import PrincipalSet

    run = await db.get(EvalRun, run_id)
    if not run:
        return
    ds = await db.get(EvalDataset, run.dataset_id)
    if not ds:
        run.status = "failed"; run.error = "数据集不存在"
        await db.commit()
        return

    qs = (await db.execute(
        select(EvalQuestion).where(EvalQuestion.dataset_id == ds.id).order_by(EvalQuestion.sort, EvalQuestion.id)
    )).scalars().all()
    run.status = "running"; run.started_at = int(time.time() * 1000)
    run.total = len(qs); run.progress = 0
    await db.commit()

    ps = PrincipalSet(user_id=run.created_by or 0, tenant_id=run.tenant_id, is_admin=True)
    kb_ids = list(ds.kb_ids or [])

    scores_f: list[float] = []
    scores_r: list[float] = []
    hits = 0
    hit_scored = 0

    for q in qs:
        t0 = time.time()
        res = EvalResult(
            tenant_id=run.tenant_id, run_id=run.id, question_id=q.id, question=q.question,
        )
        try:
            answer, usage, citations = await complete_once(
                db, ps=ps, query=q.question, kb_ids=kb_ids, top_k=top_k, use_retrieval=True,
            )
            res.answer = answer
            res.latency_ms = int((time.time() - t0) * 1000)
            ctxs = [c.snippet for c in citations if getattr(c, "snippet", None)]
            res.retrieved_chunk_ids = [c.chunk_id for c in citations if getattr(c, "chunk_id", None)]
            res.retrieved_doc_ids = sorted({c.doc_id for c in citations if getattr(c, "doc_id", None)})
            # 客观指标：期望文档是否命中
            if q.expected_doc_ids:
                hit_scored += 1
                if set(res.retrieved_doc_ids or []) & set(q.expected_doc_ids):
                    res.hit_expected = True
                    hits += 1
                else:
                    res.hit_expected = False
            # LLM 裁判
            judged = await judge_answer(
                db, tenant_id=run.tenant_id, question=q.question, answer=answer,
                contexts=ctxs, expected_answer=q.expected_answer,
            )
            if "faithfulness" in judged:
                res.faithfulness = judged["faithfulness"]; scores_f.append(judged["faithfulness"])
            if "relevance" in judged:
                res.relevance = judged["relevance"]; scores_r.append(judged["relevance"])
            res.comment = judged.get("comment")
            # 计费：评测消耗落 UsageLog
            norm = _norm_usage(usage)
            db.add(UsageLog(
                tenant_id=run.tenant_id, user_id=run.created_by, conversation_id=None,
                model_config_id=None, purpose="eval",
                prompt_tokens=norm["prompt_tokens"], completion_tokens=norm["completion_tokens"],
                total_tokens=norm["total_tokens"], cached_tokens=norm["cached_tokens"],
                latency_ms=res.latency_ms, success=True, created_at=int(time.time() * 1000),
            ))
        except Exception as e:  # noqa: BLE001
            logger.exception("eval_question_failed", qid=q.id)
            res.error = str(e)[:400]
        db.add(res)
        run.progress += 1
        await db.commit()

    run.summary = {
        "total": len(qs),
        "faithfulness": round(sum(scores_f) / len(scores_f), 2) if scores_f else None,
        "relevance": round(sum(scores_r) / len(scores_r), 2) if scores_r else None,
        "hit_rate": round(hits / hit_scored, 3) if hit_scored else None,
        "scored": len(scores_f),
    }
    run.status = "done"
    run.finished_at = int(time.time() * 1000)
    await db.commit()


def _norm_usage(raw: dict | None) -> dict:
    from app.services.usage_service import normalize_usage

    return normalize_usage(raw)
