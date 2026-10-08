"""RAG 问答质量评估测试：裁判解析、run_eval 汇总、命中率。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import EvalDataset, EvalQuestion, EvalResult, EvalRun, Tenant, User


def test_parse_judge_json_variants():
    from app.services.eval_service import _parse_judge_json

    assert _parse_judge_json('{"faithfulness": 4, "relevance": 5}')["faithfulness"] == 4
    # ``` 包裹
    assert _parse_judge_json('```json\n{"faithfulness": 3, "relevance": 3}\n```')["relevance"] == 3
    # 前后有杂字
    d = _parse_judge_json('好的：{"faithfulness": 5, "relevance": 4, "comment": "好"} 完毕')
    assert d["faithfulness"] == 5 and d["comment"] == "好"
    # 非法
    assert _parse_judge_json("没有 json") == {}
    assert _parse_judge_json("") == {}


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "eval"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="EVAL", slug="eval"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "eval_admin"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="eval_admin", password_hash=hash_password("x"),
                     is_admin=True, display_name="管理员", user_type="internal")
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "uid": u.id}


def test_run_eval_summary_and_hit(monkeypatch):
    """mock complete_once + judge → 校验汇总分与命中率。"""
    async def _run():
        d = await _setup()
        import app.services.chat_service as cs
        import app.services.eval_service as es

        # mock 问答：返回答案 + 一条 citation（doc_id=7）
        class _Cit:
            def __init__(self, doc_id):
                self.chunk_id = doc_id * 10; self.doc_id = doc_id; self.snippet = f"片段{doc_id}"
        async def _fake_complete(db, *, ps, query, kb_ids=None, top_k=5, use_retrieval=True):
            return f"答案：{query}", {"prompt_tokens": 10, "completion_tokens": 5}, [_Cit(7)]
        monkeypatch.setattr(cs, "complete_once", _fake_complete)
        # 注意 eval_service 里是 `from ... import complete_once` 在函数内导入 → patch 源
        async def _fake_judge(db, *, tenant_id, question, answer, contexts, expected_answer=None):
            return {"faithfulness": 4.0, "relevance": 5.0, "comment": "ok"}
        monkeypatch.setattr(es, "judge_answer", _fake_judge)

        async with AsyncSessionLocal() as db:
            ds = EvalDataset(tenant_id=d["tenant_id"], name="测试集", kb_ids=[], created_by=d["uid"])
            db.add(ds); await db.flush()
            db.add(EvalQuestion(tenant_id=d["tenant_id"], dataset_id=ds.id,
                                question="问题1", expected_doc_ids=[7]))
            db.add(EvalQuestion(tenant_id=d["tenant_id"], dataset_id=ds.id,
                                question="问题2", expected_doc_ids=[99]))  # 不命中
            run = EvalRun(tenant_id=d["tenant_id"], dataset_id=ds.id, created_by=d["uid"])
            db.add(run); await db.commit()
            run_id, ds_id = run.id, ds.id

        async with AsyncSessionLocal() as db:
            await es.run_eval(db, run_id=run_id, top_k=5)
            r = await db.get(EvalRun, run_id)
            assert r.status == "done"
            assert r.progress == 2 and r.total == 2
            assert r.summary["faithfulness"] == 4.0
            assert r.summary["relevance"] == 5.0
            assert r.summary["hit_rate"] == 0.5, "2 题中 1 题命中期望文档"
            res = (await db.execute(select(EvalResult).where(EvalResult.run_id == run_id))).scalars().all()
            assert len(res) == 2
            assert all(x.answer for x in res)
            # 清理
            from sqlalchemy import delete
            await db.execute(delete(EvalResult).where(EvalResult.run_id == run_id))
            await db.execute(delete(EvalQuestion).where(EvalQuestion.dataset_id == ds_id))
            await db.delete(r); await db.delete(await db.get(EvalDataset, ds_id))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())


def test_run_eval_records_usage(monkeypatch):
    async def _run():
        d = await _setup()
        import app.services.eval_service as es

        class _Cit:
            chunk_id = 1; doc_id = 1; snippet = "s"
        async def _fake_complete(db, *, ps, query, kb_ids=None, top_k=5, use_retrieval=True):
            return "ans", {"prompt_tokens": 100, "completion_tokens": 20}, [_Cit()]
        import app.services.chat_service as cs
        monkeypatch.setattr(cs, "complete_once", _fake_complete)
        async def _j(db, *, tenant_id, question, answer, contexts, expected_answer=None):
            return {}
        monkeypatch.setattr(es, "judge_answer", _j)

        async with AsyncSessionLocal() as db:
            from app.models import UsageLog
            ds = EvalDataset(tenant_id=d["tenant_id"], name="usage集", created_by=d["uid"])
            db.add(ds); await db.flush()
            db.add(EvalQuestion(tenant_id=d["tenant_id"], dataset_id=ds.id, question="q"))
            run = EvalRun(tenant_id=d["tenant_id"], dataset_id=ds.id, created_by=d["uid"])
            db.add(run); await db.commit()
            run_id, ds_id = run.id, ds.id
        async with AsyncSessionLocal() as db:
            await es.run_eval(db, run_id=run_id)
            logs = (await db.execute(select(UsageLog).where(
                UsageLog.purpose == "eval", UsageLog.tenant_id == d["tenant_id"]))).scalars().all()
            assert any(l.prompt_tokens == 100 for l in logs), "评测消耗应落 UsageLog"
            # 清理
            from sqlalchemy import delete
            await db.execute(delete(UsageLog).where(UsageLog.purpose == "eval", UsageLog.tenant_id == d["tenant_id"]))
            await db.execute(delete(EvalResult).where(EvalResult.run_id == run_id))
            await db.execute(delete(EvalQuestion).where(EvalQuestion.dataset_id == ds_id))
            await db.delete(await db.get(EvalRun, run_id)); await db.delete(await db.get(EvalDataset, ds_id))
            await db.commit()
    asyncio.new_event_loop().run_until_complete(_run())
