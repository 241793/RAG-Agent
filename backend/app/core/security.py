"""安全：密码哈希（PBKDF2，零外部依赖）与 JWT 签发/校验。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings

_PBKDF2_ITERATIONS = 200_000
_ALGO = "sha256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, hashed: str) -> bool:
    try:
        _, iters_s, salt_b64, dk_b64 = hashed.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac(_ALGO, password.encode(), salt, int(iters_s))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _create_token(payload: dict[str, Any], expires_minutes: int, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {
        **payload,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "type": token_type,
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(user_id: int, tenant_id: int, extra: dict | None = None) -> str:
    payload = {"sub": str(user_id), "tenant_id": tenant_id, **(extra or {})}
    return _create_token(payload, settings.access_token_expire_minutes, "access")


def create_refresh_token(user_id: int, tenant_id: int) -> str:
    payload = {"sub": str(user_id), "tenant_id": tenant_id}
    return _create_token(payload, settings.refresh_token_expire_minutes, "refresh")


def create_file_token(
    *,
    scope: str,
    tenant_id: int,
    file_key: str | None = None,
    artifact_id: int | None = None,
    expires_minutes: int | None = None,
) -> str:
    """签发仅用于文件读取的短期 token。

    只读、单文件、带租户，不携带用户身份/权限码——专供 <img>/<video>/<a> 等
    无法携带 Authorization 头的原生标签使用。scope 决定可访问的端点，
    file_key/artifact_id 决定可访问的具体文件。
    """
    payload: dict[str, Any] = {"scope": scope, "tenant_id": tenant_id}
    if file_key is not None:
        payload["file_key"] = file_key
    if artifact_id is not None:
        payload["artifact_id"] = artifact_id
    return _create_token(payload, expires_minutes or settings.file_token_expire_minutes, "file")


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT，失败抛 jwt.PyJWTError。"""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
