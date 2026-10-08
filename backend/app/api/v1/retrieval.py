"""检索调试接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.middleware.auth_dep import get_principal_set, require_permission
from app.schemas.chat import RetrievalRequest, RetrievalResponse
from app.services.permission import PrincipalSet
from app.services.retrieval_service import retrieve

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/query", response_model=RetrievalResponse)
async def query(
    body: RetrievalRequest,
    _guard = Depends(require_permission("retrieval:query")),
    ps: PrincipalSet = Depends(get_principal_set),
    db: AsyncSession = Depends(get_db),
) -> RetrievalResponse:
    return await retrieve(
        db,
        ps=ps,
        query=body.query,
        kb_ids=body.kb_ids,
        top_k=body.top_k,
        use_hybrid=body.use_hybrid,
        score_threshold=body.score_threshold,
        candidate_k=body.candidate_k,
        use_rerank=body.use_rerank,
    )
