"""内容安全接口：检测状态与手动检测（供运维/前端调试）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import settings
from app.middleware.auth_dep import require_permission
from app.models import User
from app.services.security_guard import detect

router = APIRouter(prefix="/security", tags=["security"])


class DetectIn(BaseModel):
    text: str


@router.get("/status")
async def guard_status(user: User = Depends(require_permission("audit:read"))) -> dict:
    return {
        "enabled": settings.security_guard_enabled,
        "block_threshold": settings.security_guard_block_threshold,
        "flag_threshold": settings.security_guard_flag_threshold,
        "wrap_context": settings.security_guard_wrap_context,
        "sensitive_word_count": len(
            [w for w in settings.security_guard_sensitive_words.split(",") if w.strip()]
        ),
        "engine": "local-rules",
    }


@router.post("/detect")
async def guard_detect(body: DetectIn, user: User = Depends(require_permission("audit:read"))) -> dict:
    sensitive = [w.strip() for w in settings.security_guard_sensitive_words.split(",") if w.strip()]
    r = detect(
        body.text,
        extra_sensitive=sensitive,
        block_threshold=settings.security_guard_block_threshold,
        flag_threshold=settings.security_guard_flag_threshold,
    )
    return {
        "risk_score": r.risk_score,
        "risk_level": r.risk_level,
        "action": r.action,
        "summary": r.summary(),
        "hits": [{"category": h.category, "rule": h.rule, "snippet": h.snippet} for h in r.hits],
    }
