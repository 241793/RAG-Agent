"""审计落库中间件：响应结束后把本请求积累的审计记录写入数据库。

用独立 session 落库，避免与业务事务纠缠（业务回滚不影响审计）。
SQLite 偶发锁冲突时做短退避重试。
"""
from __future__ import annotations

import asyncio

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import get_logger
from app.middleware.request_id import audit_buffer_ctx

logger = get_logger("audit")


class AuditFlushMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        records = audit_buffer_ctx.get()
        if records:
            await self._flush_with_retry(records)
        return response

    @staticmethod
    async def _flush_with_retry(records: list, attempts: int = 3) -> None:
        from app.core.db import AsyncSessionLocal
        from app.services.audit_service import flush_audit

        for i in range(attempts):
            try:
                async with AsyncSessionLocal() as db:
                    await flush_audit(db, records)
                return
            except Exception:  # noqa: BLE001
                if i == attempts - 1:
                    logger.exception("audit_flush_failed", count=len(records))
                else:
                    await asyncio.sleep(0.2 * (i + 1))
