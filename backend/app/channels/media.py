"""渠道媒体工具：下载入站图片/文件并解密（微信 CDN + AES-ECB）。

参考实现：机器人框架 middleware.py:3241-3295（CDN URL 拼接 + AES 解密）。
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
from pathlib import Path

import httpx

from app.core.logging import get_logger

logger = get_logger("channel.media")

WXCLAW_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
MAX_MEDIA_BYTES = 10 * 1024 * 1024   # 单文件上限 10MB
_DOWNLOAD_TIMEOUT = 30


def aes_ecb_decrypt(data: bytes, key_b64: str) -> bytes:
    """微信媒体解密：key 是 base64(hex_string)；AES-ECB + PKCS7。失败抛异常。"""
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def _norm_key(k: bytes) -> bytes | None:
        return k if len(k) in (16, 24, 32) else None

    key = None
    # 1) 若整体就是合法 hex 且长度正确 → 直接用（裸 hex）
    try:
        hk = bytes.fromhex(key_b64)
        key = _norm_key(hk)
    except Exception:  # noqa: BLE001
        key = None
    # 2) 否则 base64 解码，再尝试 hex / 直接用
    if key is None:
        try:
            raw = base64.b64decode(key_b64 + "=" * (-len(key_b64) % 4))
        except Exception:  # noqa: BLE001
            raw = b""
        if raw:
            try:
                key = _norm_key(bytes.fromhex(raw.decode("ascii")))
            except Exception:  # noqa: BLE001
                key = None
            if key is None:
                key = _norm_key(raw)
    if key is None:
        key = b"\0" * 16
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    dec = cipher.decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """微信媒体加密（发送用）：AES-ECB + PKCS7。"""
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def _wxclaw_cdn_urls(eqp: str) -> list[str]:
    """由 encrypt_query_param 拼多个候选 CDN 下载地址。"""
    from urllib.parse import quote

    eqp = (eqp or "").strip().strip("\"'` \t\n\r")
    urls: list[str] = []
    if eqp.startswith(("http://", "https://")):
        urls.append(eqp)
        return urls
    urls.append(f"{WXCLAW_CDN_BASE}/download?encrypted_query_param={quote(eqp, safe='')}")
    urls.append(f"{WXCLAW_CDN_BASE}?encrypted_query_param={quote(eqp, safe='')}")
    idx = eqp.find("https://")
    if idx < 0:
        idx = eqp.find("http://")
    if idx >= 0:
        urls.insert(0, eqp[idx:].strip("\"'` \t\n\r"))
    return urls


def guess_ext(name: str | None, data: bytes | None = None) -> str:
    if name:
        ext = Path(name).suffix
        if ext:
            return ext.lstrip(".")
    if data:
        # 简单魔数嗅探
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        if data[:3] == b"\xff\xd8\xff":
            return "jpg"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "gif"
        if data[:4] == b"%PDF":
            return "pdf"
    return "bin"


async def _download_wxclaw(att: dict) -> bytes | None:
    """微信：CDN 下载 + AES 解密。att 含 url 或 encrypt_query_param + aes_key。"""
    eqp = att.get("url") or att.get("encrypt_query_param") or ""
    aes_key = att.get("aes_key") or ""
    for url in _wxclaw_cdn_urls(eqp):
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as c:
                r = await c.get(url)
            if r.status_code != 200 or len(r.content) < 16:
                continue
            body = r.content
            if len(body) > MAX_MEDIA_BYTES:
                logger.warning("media_too_large", size=len(body))
                return None
            if aes_key:
                try:
                    body = aes_ecb_decrypt(body, aes_key)
                except Exception:  # noqa: BLE001
                    logger.warning("media_decrypt_failed", url=url[:80])
                    # 解密失败保留原始（可能是明文）
            return body
        except Exception:  # noqa: BLE001
            continue
    return None


async def _download_direct(att: dict) -> bytes | None:
    url = att.get("url") or ""
    if not url.startswith(("http://", "https://")):
        return None
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(url, headers=att.get("headers") or None)
        if r.status_code != 200 or not r.content:
            return None
        if len(r.content) > MAX_MEDIA_BYTES:
            return None
        return r.content
    except Exception:  # noqa: BLE001
        return None


async def _download_feishu(att: dict) -> bytes | None:
    """飞书：图片用 im/v1/images/{key}，文件用 im/v1/messages/{mid}/resources/{key}。"""
    cfg = att.get("_feishu_cfg") or {}
    app_id, app_secret = cfg.get("app_id"), cfg.get("app_secret")
    if not app_id or not app_secret:
        return None
    key = att.get("key")
    kind = att.get("feishu_kind")  # image|file
    message_id = att.get("message_id")
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as c:
            tr = await c.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            tok = tr.json().get("tenant_access_token")
            if not tok:
                return None
            headers = {"Authorization": f"Bearer {tok}"}
            if kind == "image":
                url = f"https://open.feishu.cn/open-apis/im/v1/images/{key}?type=message"
            else:
                if not message_id:
                    return None
                url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{key}?type=file"
            r = await c.get(url, headers=headers)
        if r.status_code != 200 or len(r.content) < 10:
            return None
        if len(r.content) > MAX_MEDIA_BYTES:
            return None
        return r.content
    except Exception:  # noqa: BLE001
        return None


async def download_media(att: dict) -> tuple[bytes | None, str | None]:
    """下载一条附件，返回 (bytes, ext)。失败 (None, None)。

    att 结构见 base.InboundMessage.attachments。
    """
    if att.get("data"):
        data = att["data"]
        return data, guess_ext(att.get("name"), data)
    channel = att.get("_channel") or ""
    if att.get("feishu_kind"):
        data = await _download_feishu(att)
    elif att.get("mediaid"):
        data = await _download_wework(att)   # 企微：需调 getmedia（凭证由 dispatcher 注入）
    elif channel == "wxclaw" or att.get("aes_key") or att.get("encrypt_query_param"):
        data = await _download_wxclaw(att)
    else:
        data = await _download_direct(att)
    if not data:
        return None, None
    return data, guess_ext(att.get("name"), data)


async def _download_wework(att: dict) -> bytes | None:
    """企业微信媒体下载：需 bot 凭证 + getmedia 接口。

    aibot 媒体下载地址由平台提供；此处按常见形态尝试，缺失凭证则失败降级。
    """
    cfg = att.get("_wework_cfg") or {}
    base = cfg.get("base_url")
    if not base:
        return None
    mediaid = att.get("mediaid")
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as c:
            r = await c.get(f"{base.rstrip('/')}/cgi-bin/media/get", params={"media_id": mediaid})
        if r.status_code == 200 and r.content and len(r.content) > 10:
            return r.content
    except Exception:  # noqa: BLE001
        return None
    return None


def mime_of(name: str | None, ext: str | None) -> str:
    if name:
        mt = mimetypes.guess_type(name)[0]
        if mt:
            return mt
    if ext:
        return mimetypes.guess_type(f"x.{ext}")[0] or "application/octet-stream"
    return "application/octet-stream"


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def rand_hex(n: int = 16) -> str:
    return os.urandom(n).hex()
