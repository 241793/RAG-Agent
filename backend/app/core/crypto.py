"""外部源凭证的对称加密（Fernet）。

用途单一：KnowledgeBase.connector_config 里的 api_key。
- 密文形如 "enc:<token>"；解密时无前缀者原样返回（兼容存量明文）。
- 密钥由 settings.secret_key 经 SHA256 派生 32 字节，避免引入额外的密钥管理。
"""
from __future__ import annotations

import base64
import hashlib

_PREFIX = "enc:"


def _fernet():
    from cryptography.fernet import Fernet

    from app.core.config import settings

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt(plain: str | None) -> str | None:
    if not plain:
        return plain
    token = _fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt(val: str | None) -> str | None:
    if not val:
        return val
    if not val.startswith(_PREFIX):
        return val  # 兼容未加密的历史值
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(val[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""  # 密钥变更导致无法解密：返回空而非抛错，避免整体检索失败


def mask(val: str | None) -> str:
    """仅供展示：明文只回显首尾各 2 位。"""
    if not val:
        return ""
    plain = decrypt(val) or ""
    if len(plain) <= 4:
        return "••••"
    return f"{plain[:2]}••••{plain[-2:]}"
