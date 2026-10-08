"""外部渠道测试：抽象、身份解析、指令、dispatcher、各驱动 parse/send（mock）。"""
from __future__ import annotations

import asyncio

import pytest

from app.channels.base import InboundMessage, OutboundMessage
from app.channels.commands import COMMANDS, is_command, parse_command
from app.core.errors import ValidationError


# ---- 抽象层 ----
def test_outbound_defaults():
    m = OutboundMessage(content="hi", user_id="u1")
    assert m.content_type == "text" and m.group_id is None


def test_inbound_defaults():
    m = InboundMessage(channel="qqbot", external_user="u1", content="hi")
    assert m.is_group is False and m.raw == {}


# ---- 指令解析 ----
def test_parse_command():
    assert parse_command("/kb use 1") == ("kb", ["use", "1"])
    assert parse_command("/help") == ("help", [])
    assert parse_command("/") == ("help", [])


def test_is_command():
    assert is_command("/help") is True
    assert is_command("你好") is False
    assert is_command("") is False


def test_all_commands_registered():
    for name in ("help", "kb", "agent", "new", "whoami"):
        assert name in COMMANDS


def test_custom_prefix():
    assert is_command("!help", "!") is True
    assert parse_command("!kb list", "!") == ("kb", ["list"])


# ---- 注册表 ----
def test_build_adapter_all_kinds():
    from app.channels.registry import build_adapter

    async def _cb(m):
        return None

    assert build_adapter("qqbot", config={"app_id": "a", "client_secret": "b"}, on_message=_cb).__class__.__name__ == "QQBotAdapter"
    assert build_adapter("wxclaw", config={"api_url": "http://x", "token": "t"}, on_message=_cb).__class__.__name__ == "WxClawAdapter"
    assert build_adapter("wework", config={"bot_id": "b", "secret": "s"}, on_message=_cb).__class__.__name__ == "WeWorkAdapter"
    assert build_adapter("feishu", config={"app_id": "a", "app_secret": "s"}, on_message=_cb).__class__.__name__ == "FeishuAdapter"


def test_build_adapter_missing_config():
    from app.channels.registry import build_adapter

    with pytest.raises(ValidationError):
        build_adapter("qqbot", config={}, on_message=None)
    with pytest.raises(ValidationError):
        build_adapter("nope", config={}, on_message=None)


# ---- 各驱动 parse_message（纯函数级，不连网）----
def test_qqbot_parse_c2c():
    from app.channels.drivers.qqbot import QQBotAdapter

    a = QQBotAdapter(config={"app_id": "a", "client_secret": "b"}, on_message=None)
    msg = a.parse_event("C2C_MESSAGE_CREATE", {
        "author": {"user_openid": "USER1"}, "content": "你好", "id": "MID1",
    })
    assert msg.external_user == "USER1" and msg.content == "你好" and not msg.is_group


def test_qqbot_parse_group_strips_mention():
    from app.channels.drivers.qqbot import QQBotAdapter

    a = QQBotAdapter(config={"app_id": "a", "client_secret": "b"}, on_message=None)
    msg = a.parse_event("GROUP_AT_MESSAGE_CREATE", {
        "author": {"member_openid": "U2"}, "content": "<@!123> 提问",
        "group_openid": "G1", "id": "MID2",
    })
    assert msg.is_group and msg.external_group == "G1" and msg.content == "提问"


def test_wxclaw_parse_text():
    from app.channels.drivers.wxclaw import WxClawAdapter

    a = WxClawAdapter(config={"api_url": "http://x", "token": "t"}, on_message=None)
    msg = a.parse_message({
        "message_type": 1, "from_user_id": "WXU1", "context_token": "CT1",
        "item_list": [{"type": 1, "text_item": {"text": "hello"}}], "message_id": "M1",
    })
    assert msg.external_user == "WXU1" and msg.content == "hello"
    assert a._context["WXU1"]["token"] == "CT1"


def test_wxclaw_parse_image():
    from app.channels.drivers.wxclaw import WxClawAdapter

    a = WxClawAdapter(config={"api_url": "http://x", "token": "t"}, on_message=None)
    msg = a.parse_message({
        "message_type": 1, "from_user_id": "U", "item_list": [{"type": 2, "image_item": {}}],
    })
    assert "[图片]" in msg.content


def test_wework_parse_text():
    from app.channels.drivers.wework import WeWorkAdapter

    a = WeWorkAdapter(config={"bot_id": "b", "secret": "s"}, on_message=None)
    msg = a.parse_message({
        "from": {"userid": "WU1"}, "msgtype": "text", "text": {"content": "hi"},
        "chattype": "single", "msgid": "M1",
    }, req_id="R1")
    assert msg.external_user == "WU1" and msg.content == "hi"
    assert a._req_ids["WU1"] == "R1"


def test_wework_parse_group():
    from app.channels.drivers.wework import WeWorkAdapter

    a = WeWorkAdapter(config={"bot_id": "b", "secret": "s"}, on_message=None)
    msg = a.parse_message({
        "from": {"userid": "WU1"}, "msgtype": "text", "text": {"content": "hi"},
        "chattype": "group", "chatid": "C1", "msgid": "M1",
    })
    assert msg.is_group and msg.external_group == "C1"


def test_feishu_parse_text():
    from app.channels.drivers.feishu import FeishuAdapter

    a = FeishuAdapter(config={"app_id": "a", "app_secret": "s"}, on_message=None)
    msg = a.parse_event({
        "event": {
            "chat_type": "p2p", "chat_id": "C1",
            "message": {"message_type": "text", "content": '{"text":"你好"}', "message_id": "M1"},
            "sender": {"sender_id": {"open_id": "OU1"}},
        }
    })
    assert msg.external_user == "OU1" and msg.content == "你好" and not msg.is_group


def test_feishu_parse_group():
    from app.channels.drivers.feishu import FeishuAdapter

    a = FeishuAdapter(config={"app_id": "a", "app_secret": "s"}, on_message=None)
    msg = a.parse_event({
        "event": {
            "chat_type": "group", "chat_id": "GC1",
            "message": {"message_type": "text", "content": '{"text":"hi"}', "message_id": "M2"},
            "sender": {"sender_id": {"open_id": "OU2"}},
        }
    })
    assert msg.is_group and msg.external_group == "GC1"


# ---- 出站 URL/请求体（mock httpx）----
@pytest.mark.asyncio
async def test_feishu_send_uses_correct_receive_id_type(monkeypatch):
    from app.channels.drivers import feishu as fmod

    calls = {}

    class FakeResp:
        def json(self): return {"code": 0}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            calls["url"] = url
            calls["params"] = kw.get("params")
            calls["json"] = kw.get("json")
            return FakeResp()

    monkeypatch.setattr(fmod.httpx, "AsyncClient", FakeClient)

    a = fmod.FeishuAdapter(config={"app_id": "a", "app_secret": "s"}, on_message=None)
    a._token = "tk"; a._token_expire = 9e18

    ok = await a.send_message(OutboundMessage(content="hi", user_id="ou_abc"))
    assert ok is True
    assert calls["params"]["receive_id_type"] == "open_id"
    assert calls["json"]["receive_id"] == "ou_abc"


@pytest.mark.asyncio
async def test_qqbot_send_body(monkeypatch):
    from app.channels.drivers import qqbot as qmod

    calls = {}

    class FakeResp:
        def __init__(self, data): self._d = data
        @property
        def text(self): return "{}"
        def json(self): return self._d
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, method, url, **kw):
            calls["url"] = url; calls["json"] = kw.get("json")
            return FakeResp({"code": 0})

    monkeypatch.setattr(qmod.httpx, "AsyncClient", FakeClient)

    a = qmod.QQBotAdapter(config={"app_id": "a", "client_secret": "b"}, on_message=None)
    a._token = "tk"; a._token_expire = 9e18
    a._sessions["USER1"] = {"msg_id": "MID", "is_group": False}

    ok = await a.send_message(OutboundMessage(content="hi", user_id="USER1"))
    assert ok is True
    assert "/v2/users/USER1/messages" in calls["url"]
    assert calls["json"]["content"] == "hi" and calls["json"]["msg_id"] == "MID"


# ---- 端点注册 ----
def test_channel_endpoints_registered():
    from app.api.v1.channels import router

    paths = {r.path for r in router.routes}
    assert "/channels" in paths
    assert "/channels/{channel_id}" in paths
    assert "/channels/{channel_id}/test" in paths
    assert "/channels/{channel_id}/users" in paths
    assert "/channels/callback/{channel_id}" in paths


def test_permissions_seeded():
    from app.services.permission_seed import PERMISSIONS

    codes = {p[0] for p in PERMISSIONS}
    assert "channel:read" in codes and "channel:manage" in codes
