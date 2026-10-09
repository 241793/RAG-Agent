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


def create_access_token(
    user_id: int, tenant_id: int, extra: dict | None = None, token_version: int = 0
) -> str:
    payload = {"sub": str(user_id), "tenant_id": tenant_id, "tv": token_version, **(extra or {})}
    return _create_token(payload, settings.access_token_expire_minutes, "access")


def create_refresh_token(user_id: int, tenant_id: int, token_version: int = 0) -> str:
    payload = {"sub": str(user_id), "tenant_id": tenant_id, "tv": token_version}
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


# 常见弱密码（含默认种子密码），不区分大小写
_WEAK_PASSWORDS = {
    "password", "passw0rd", "123456", "12345678", "123456789", "1234567890",
    "qwerty", "qwerty123", "abc123", "111111", "000000", "admin", "admin123",
    "root", "letmein", "iloveyou", "welcome", "monkey", "dragon", "sunshine",
    "princess", "football", "baseball", "master", "666666", "888888", "123123",
    "admin888", "administrator", "test123", "a123456", "p@ssw0rd", "1qaz2wsx",
}
_MIN_PASSWORD_LEN = 8


def check_password_strength(password: str) -> tuple[bool, str]:
    """密码强度校验：长度 + 字符种类 + 弱密码黑名单。返回 (是否通过, 原因)。

    不强求大小写混合——把「字母」视为一类（不分大小写），与数字、符号合计
    三类中满足至少两类即可。即：纯小写字母 + 数字（如 abc12345）可通过。
    """
    p = password or ""
    if len(p) < _MIN_PASSWORD_LEN:
        return False, f"密码至少 {_MIN_PASSWORD_LEN} 位"
    if len(p) > 128:
        return False, "密码不能超过 128 位"
    if p.lower() in _WEAK_PASSWORDS:
        return False, "密码过于常见，请更换更复杂的密码"
    # 类别：字母（不分大小写）/ 数字 / 符号
    kinds = 0
    if any(c.isalpha() for c in p):
        kinds += 1
    if any(c.isdigit() for c in p):
        kinds += 1
    if any(not c.isalnum() for c in p):
        kinds += 1
    if kinds < 2:
        return False, "密码需包含字母、数字、符号中的至少两类"
    return True, ""


def validate_password_or_raise(password: str) -> None:
    """校验失败抛 ValidationError（供 API 层复用）。"""
    from app.core.errors import ValidationError

    ok, reason = check_password_strength(password)
    if not ok:
        raise ValidationError(reason)
