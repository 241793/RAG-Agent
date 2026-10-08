"""API Key 服务：生成、哈希、校验。"""
from __future__ import annotations

import hashlib
import secrets

PREFIX = "sk-rag-"


def generate_key() -> tuple[str, str, str]:
    """返回 (明文, key_prefix, key_hash)。明文只在创建时返回一次。"""
    raw = PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_key(raw)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
