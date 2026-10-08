"""渠道媒体测试：AES 加解密、下载 URL 拼接、各驱动 parse 附件、dispatcher 落盘。"""
from __future__ import annotations

import base64
import os

import pytest


# ---- AES ----
def test_aes_roundtrip():
    from app.channels import media

    key = os.urandom(16)
    data = b"hello media content" * 20
    enc = media.aes_ecb_encrypt(data, key)
    key_b64 = base64.b64encode(key.hex().encode("ascii")).decode()
    assert media.aes_ecb_decrypt(enc, key_b64) == data


def test_aes_decrypt_hex_key_direct():
    """key 也可能是纯 hex 字符串（非 base64 包裹）。"""
    from app.channels import media

    key = os.urandom(16)
    data = b"abc" * 33
    enc = media.aes_ecb_encrypt(data, key)
    # 标准：base64(hex_string)
    assert media.aes_ecb_decrypt(enc, base64.b64encode(key.hex().encode()).decode()) == data
    # 裸 hex 兼容
    assert media.aes_ecb_decrypt(enc, key.hex()) == data


def test_guess_ext():
    from app.channels import media

    assert media.guess_ext("a.png") == "png"
    assert media.guess_ext(None, b"\x89PNG\r\n\x1a\nxxxx") == "png"
    assert media.guess_ext(None, b"\xff\xd8\xffxxx") == "jpg"
    assert media.guess_ext(None, b"%PDF-1.4") == "pdf"


def test_wxclaw_cdn_urls():
    from app.channels import media

    urls = media._wxclaw_cdn_urls("ABC123")
    assert any("novac2c.cdn.weixin.qq.com" in u for u in urls)
    assert any("encrypted_query_param=ABC123" in u for u in urls)
    # 完整 URL 直接返回
    assert media._wxclaw_cdn_urls("https://x/y.jpg") == ["https://x/y.jpg"]


# ---- 各驱动 parse 附件 ----
def test_wxclaw_parse_image_attachment():
    from app.channels.drivers.wxclaw import WxClawAdapter

    a = WxClawAdapter(config={"api_url": "http://x", "token": "t"}, on_message=None)
    msg = a.parse_message({
        "message_type": 1, "from_user_id": "U1", "context_token": "C",
        "item_list": [{"type": 2, "image_item": {
            "media": {"full_url": "http://cdn/img", "aes_key": "K", "encrypt_query_param": "E"},
        }}],
    })
    assert msg and len(msg.attachments) == 1
    att = msg.attachments[0]
    assert att["type"] == "image" and att["aes_key"] == "K" and att["encrypt_query_param"] == "E"


def test_wxclaw_parse_file_attachment():
    from app.channels.drivers.wxclaw import WxClawAdapter

    a = WxClawAdapter(config={"api_url": "http://x", "token": "t"}, on_message=None)
    msg = a.parse_message({
        "message_type": 1, "from_user_id": "U1",
        "item_list": [{"type": 4, "file_item": {"filename": "报表.pdf",
                                                "media": {"encrypt_query_param": "P", "aes_key": "K"}}}],
    })
    assert msg.attachments[0]["name"] == "报表.pdf"


def test_qqbot_parse_attachment():
    from app.channels.drivers.qqbot import QQBotAdapter

    a = QQBotAdapter(config={"app_id": "a", "client_secret": "b"}, on_message=None)
    a._token = "TK"
    msg = a.parse_event("C2C_MESSAGE_CREATE", {
        "author": {"user_openid": "U"}, "content": "看图", "id": "M",
        "attachments": [{"content_type": "image/png", "url": "http://x/a.png", "filename": "a.png"}],
    })
    assert len(msg.attachments) == 1
    assert msg.attachments[0]["type"] == "image"
    assert msg.attachments[0]["headers"]["Authorization"] == "QQBot TK"


def test_feishu_parse_image_attachment():
    from app.channels.drivers.feishu import FeishuAdapter

    a = FeishuAdapter(config={"app_id": "ai", "app_secret": "as"}, on_message=None)
    msg = a.parse_event({"event": {
        "message": {"chat_type": "p2p", "chat_id": "C", "message_type": "image",
                    "content": '{"image_key":"img_1"}', "message_id": "M1"},
        "sender": {"sender_id": {"open_id": "OU"}},
    }})
    assert len(msg.attachments) == 1
    assert msg.attachments[0]["feishu_kind"] == "image"
    assert msg.attachments[0]["key"] == "img_1"


def test_wework_parse_file_attachment():
    from app.channels.drivers.wework import WeWorkAdapter

    a = WeWorkAdapter(config={"bot_id": "b", "secret": "s"}, on_message=None)
    msg = a.parse_message({
        "from": {"userid": "U"}, "msgtype": "file", "chattype": "single",
        "file": {"mediaid": "MID", "filename": "doc.pdf", "aeskey": "AK"},
    }, req_id="R")
    assert msg.attachments[0]["mediaid"] == "MID"
    assert msg.attachments[0]["name"] == "doc.pdf"


# ---- download_media（mock httpx）----
@pytest.mark.asyncio
async def test_download_media_direct(monkeypatch):
    from app.channels import media

    class FakeResp:
        status_code = 200
        content = b"\x89PNG\r\n\x1a\n" + b"x" * 100

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return FakeResp()

    monkeypatch.setattr(media.httpx, "AsyncClient", FakeClient)
    data, ext = await media.download_media({"type": "image", "url": "http://x/a.png"})
    assert data and ext == "png"


@pytest.mark.asyncio
async def test_download_media_uses_inline_data():
    from app.channels import media

    data, ext = await media.download_media({"type": "file", "name": "a.pdf", "data": b"%PDF-1.4 xx"})
    assert ext == "pdf" and data.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_wxclaw_download_decrypts(monkeypatch):
    """微信 CDN 下载 + AES 解密全链路。"""
    from app.channels import media

    key = os.urandom(16)
    plain = b"real image bytes" * 10
    enc = media.aes_ecb_encrypt(plain, key)
    key_b64 = base64.b64encode(key.hex().encode()).decode()

    class FakeResp:
        status_code = 200
        content = enc

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return FakeResp()

    monkeypatch.setattr(media.httpx, "AsyncClient", FakeClient)
    data, _ = await media.download_media({
        "type": "image", "name": "i.png", "encrypt_query_param": "EQP",
        "aes_key": key_b64, "_channel": "wxclaw",
    })
    assert data == plain
