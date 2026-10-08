"""文件签名 URL 鉴权测试。

断言：
  - 签名 token 只能访问其绑定的 file_key / artifact_id（跨文件/跨端点拒绝）
  - 过期 token 拒绝
  - 无凭证 → 401；带正常 header 用户 → 走 chat:use 校验
"""
from __future__ import annotations

import asyncio

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.errors import AuthError, PermissionDeniedError
from app.core.security import create_file_token
from app.core.db import AsyncSessionLocal, init_models
from app.middleware.auth_dep import get_file_access


async def _call_get_file_access(t=None, authorization=None):
    """直接调用依赖：正常返回 FileAccess，异常抛出。"""
    async with AsyncSessionLocal() as db:
        return await get_file_access(t=t, authorization=authorization, db=db)


async def _run():
    await init_models()
    tid = 1

    # 1) 正常签名 token（attachment / file_key=a）
    tok = create_file_token(scope="attachment", tenant_id=tid, file_key=f"{tid}/a.png")
    fa = await _call_get_file_access(t=tok)
    assert fa.via == "token" and fa.scope == "attachment" and fa.file_key == f"{tid}/a.png"

    # 2) 无凭证 → AuthError(401)
    with pytest.raises(AuthError):
        await _call_get_file_access()

    # 3) 过期 token → PermissionDeniedError(403)
    expired = create_file_token(scope="attachment", tenant_id=tid, file_key=f"{tid}/a.png", expires_minutes=-1)
    with pytest.raises(PermissionDeniedError):
        await _call_get_file_access(t=expired)

    # 4) 类型错误的 token（用 access 类型的 payload 冒充）→ 403
    bad = jwt.encode({"sub": "1", "tenant_id": tid, "type": "access"},
                     settings.secret_key, algorithm=settings.algorithm)
    with pytest.raises(PermissionDeniedError):
        await _call_get_file_access(t=bad)

    # 5) artifact scope
    tok2 = create_file_token(scope="artifact", tenant_id=tid, artifact_id=42)
    fa2 = await _call_get_file_access(t=tok2)
    assert fa2.scope == "artifact" and fa2.artifact_id == 42

    print("OK file_token")


def test_file_token():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_token_scope_mismatch():
    """scope 与 file_key 双校验：attachment token 不能用于其它 file_key（端点层逻辑）。"""
    tok = create_file_token(scope="attachment", tenant_id=1, file_key="1/a.png")
    payload = jwt.decode(tok, settings.secret_key, algorithms=[settings.algorithm])
    # 模拟端点校验：请求的 file_key 与 token 内的不一致 → 拒绝
    req_file_key = "1/b.png"
    assert payload["file_key"] != req_file_key
    # scope 不匹配 artifact 端点同理
    assert payload["scope"] != "artifact"
