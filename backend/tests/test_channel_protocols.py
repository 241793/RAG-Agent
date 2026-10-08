"""渠道协议修复回归：feishu 群聊字段、wework stream/chat_type、qqbot seq/session、wxclaw 扫码。"""
from __future__ import annotations

import asyncio
import json

import pytest


# ---- feishu：chat_type/chat_id 在 event.message 上（真实 lark 结构）----
def test_feishu_group_from_message_level():
    from app.channels.drivers.feishu import FeishuAdapter

    f = FeishuAdapter(config={"app_id": "a", "app_secret": "s"}, on_message=None)
    # 真实结构：chat_type/chat_id 在 message，不在 event
    m = f.parse_event({"event": {
        "message": {"chat_type": "group", "chat_id": "GC1", "message_type": "text",
                    "content": '{"text":"群消息"}', "message_id": "M1"},
        "sender": {"sender_id": {"open_id": "OU1"}},
    }})
    assert m.is_group is True
    assert m.external_group == "GC1"
    assert m.content == "群消息"


def test_feishu_p2p_from_message_level():
    from app.channels.drivers.feishu import FeishuAdapter

    f = FeishuAdapter(config={"app_id": "a", "app_secret": "s"}, on_message=None)
    m = f.parse_event({"event": {
        "message": {"chat_type": "p2p", "chat_id": "C1", "message_type": "text",
                    "content": '{"text":"私聊"}', "message_id": "M2"},
        "sender": {"sender_id": {"open_id": "OU2"}},
    }})
    assert m.is_group is False and m.external_group is None


def test_feishu_object_path_reads_message(monkeypatch):
    """_parse_lark_event 从对象 event.message.chat_type 读（防回归）。"""
    from app.channels.drivers.feishu import FeishuAdapter

    class Obj:
        def __init__(self, **kw): self.__dict__.update(kw)

    f = FeishuAdapter(config={"app_id": "a", "app_secret": "s"}, on_message=None)
    data = Obj(event=Obj(
        message=Obj(chat_type="group", chat_id="GC9", message_type="text",
                    content='{"text":"x"}', message_id="M9"),
        sender=Obj(sender_id=Obj(open_id="OU9")),
    ))
    m = f._parse_lark_event(data)
    assert m is not None and m.is_group and m.external_group == "GC9"


# ---- wework：被动回复 stream 两帧；主动推送 chat_type 判定 ----
@pytest.mark.asyncio
async def test_wework_respond_uses_stream_frames():
    from app.channels.drivers.wework import WeWorkAdapter
    from app.channels.base import OutboundMessage

    sent = []

    class FakeWS:
        async def send(self, data): sent.append(json.loads(data))

    a = WeWorkAdapter(config={"bot_id": "b", "secret": "s"}, on_message=None)
    a._ws = FakeWS()
    a._req_ids["USER1"] = "REQ1"

    ok = await a.send_message(OutboundMessage(content="hi", user_id="USER1"))
    assert ok is True
    assert len(sent) == 2
    assert all(f["cmd"] == "aibot_respond_msg" for f in sent)
    assert sent[0]["body"]["msgtype"] == "stream"
    assert sent[0]["body"]["stream"]["finish"] is False
    assert sent[1]["body"]["stream"]["finish"] is True
    assert sent[0]["headers"]["req_id"] == "REQ1"


@pytest.mark.asyncio
async def test_wework_proactive_group_chat_type():
    from app.channels.drivers.wework import WeWorkAdapter
    from app.channels.base import OutboundMessage

    sent = []

    class FakeWS:
        async def send(self, data): sent.append(json.loads(data))

    a = WeWorkAdapter(config={"bot_id": "b", "secret": "s"}, on_message=None)
    a._ws = FakeWS()

    # 群 id（长/@ 开头）→ chat_type=2
    await a.send_message(OutboundMessage(content="grp", group_id="GROUPID_LONG_1234567890"))
    assert sent[-1]["cmd"] == "aibot_send_msg"
    assert sent[-1]["body"]["chat_type"] == 2

    # 短 user id → chat_type=1
    await a.send_message(OutboundMessage(content="dm", user_id="u1"))
    assert sent[-1]["body"]["chat_type"] == 1


# ---- qqbot：seq 更新 / session / Resume 判定 ----
@pytest.mark.asyncio
async def test_qqbot_seq_and_session_updated():
    from app.channels.drivers.qqbot import QQBotAdapter, OP_DISPATCH, OP_HELLO, OP_IDENTIFY

    a = QQBotAdapter(config={"app_id": "a", "client_secret": "b"}, on_message=None)
    a._token = "tk"; a._token_expire = 9e18
    a._conn_start = 0  # 新连接，不可 Resume

    class FakeWS:
        def __init__(self): self.frames = []
        async def send(self, data): self.frames.append(json.loads(data))
        async def close(self): pass

    ws = FakeWS()
    # Hello → 应发 Identify（无 session）
    await a._handle_payload(ws, {"op": OP_HELLO, "d": {"heartbeat_interval": 30000}})
    assert ws.frames[-1]["op"] == OP_IDENTIFY

    # Dispatch READY → 存 session_id
    await a._handle_payload(ws, {"op": OP_DISPATCH, "t": "READY", "s": 42, "d": {"session_id": "SESS1"}})
    assert a._session_id == "SESS1"
    assert a._last_seq == 42  # seq 已更新

    if a._heartbeat_task:
        a._heartbeat_task.cancel()


# ---- wxclaw：扫码解析 + 固定地址 + account 写入 ----
def test_wxclaw_extract_login_payload_variants():
    from app.channels import wxclaw_login

    p = wxclaw_login.extract_login_payload({"data": {
        "access_token": "tokA", "qrcode_img_content": "http://q/img.png",
        "uuid": "tickA", "state": "wait", "ilink_user_id": "botA",
    }})
    assert p["token"] == "tokA" and p["qr"] == "http://q/img.png"
    assert p["ticket"] == "tickA" and p["bot_id"] == "botA"
    # 顶层无 data 也应解析
    p2 = wxclaw_login.extract_login_payload({"token": "t2", "qrcode": "q2"})
    assert p2["token"] == "t2" and p2["ticket"] == "q2"


def test_wxclaw_fixed_url_shape():
    from app.channels import wxclaw_login

    assert wxclaw_login.FIXED_API_URL == "https://ilinkai.weixin.qq.com"
    u = wxclaw_login.normalize_url(wxclaw_login.FIXED_API_URL, wxclaw_login.LOGIN_QR_PATH)
    assert u == "https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode"


def test_wxclaw_upsert_account_dedup():
    from app.channels import wxclaw_login

    cfg = {}
    cfg = wxclaw_login.upsert_account(cfg, token="T1", api_url=wxclaw_login.FIXED_API_URL, bot_id="B1")
    assert cfg["token"] == "T1" and len(cfg["accounts"]) == 1
    assert cfg["api_url"] == wxclaw_login.FIXED_API_URL
    # 同 token 再写 → 不新增
    cfg = wxclaw_login.upsert_account(cfg, token="T1", api_url=wxclaw_login.FIXED_API_URL, bot_id="B1")
    assert len(cfg["accounts"]) == 1


@pytest.mark.asyncio
async def test_wxclaw_build_display_qr(monkeypatch):
    from app.channels import wxclaw_login

    class FakeResp:
        status_code = 200
        headers = {"Content-Type": "image/png"}
        content = b"\x89PNG-fake"
        text = ""

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **k): return FakeResp()

    monkeypatch.setattr(wxclaw_login.httpx, "AsyncClient", FakeClient)
    data_url = await wxclaw_login.build_display_qr("http://weixin.qq.com/x")
    assert data_url.startswith("data:image/png;base64,")


def test_wxclaw_scan_endpoints_registered():
    from app.api.v1.channels import router

    paths = {r.path for r in router.routes}
    assert "/channels/{channel_id}/wxclaw/scan-login" in paths
    assert "/channels/{channel_id}/wxclaw/login-status" in paths
    assert "/channels/wxclaw/scan" in paths
    assert "/channels/wxclaw/scan-status" in paths


@pytest.mark.asyncio
async def test_wxclaw_send_payload_structure(monkeypatch):
    """回归：发送必须用 {msg:{...}, base_info:{...}} 结构（含 client_id / message_type=2 / context_token 在 msg 内）。

    这是"只打通接收、发不出去"的根因修复：扁平 payload 缺 client_id 被上游拒收。
    """
    import json as _json
    import time as _time

    from app.channels.drivers import wxclaw as wmod
    from app.channels.base import OutboundMessage

    captured = {}

    class FakeResp:
        status_code = 200
        text = '{"ret":0}'
        def json(self): return {"ret": 0}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            captured["url"] = url
            captured["json"] = kw.get("json")
            return FakeResp()

    monkeypatch.setattr(wmod.httpx, "AsyncClient", FakeClient)
    a = wmod.WxClawAdapter(config={"api_url": "http://x", "token": "tok"}, on_message=None)
    a._context["U1"] = {"token": "CTX", "ts": _time.time()}

    ok = await a.send_message(OutboundMessage(content="你好", user_id="U1"))
    assert ok is True
    body = captured["json"]
    assert set(body.keys()) == {"msg", "base_info"}
    m = body["msg"]
    assert m["to_user_id"] == "U1"
    assert m["context_token"] == "CTX"          # 必须在 msg 内
    assert m["message_type"] == 2               # 参考实现用 2
    assert m["client_id"]                        # 必填
    assert "context_token" not in body           # 顶层不应有
    assert body["base_info"]["channel_version"]  # base_info 必填
    assert m["item_list"][0]["text_item"]["text"] == "你好"


@pytest.mark.asyncio
async def test_wxclaw_send_skips_without_context(monkeypatch):
    """无 context_token（用户未互动/超 24h）时不应尝试发送。"""
    from app.channels.drivers import wxclaw as wmod
    from app.channels.base import OutboundMessage

    a = wmod.WxClawAdapter(config={"api_url": "http://x", "token": "tok"}, on_message=None)
    ok = await a.send_message(OutboundMessage(content="hi", user_id="NOBODY"))
    assert ok is False


@pytest.mark.asyncio
async def test_wxclaw_check_status_timeout_returns_empty(monkeypatch):
    """长轮询读超时 → 返回空 dict（不是抛错），上层据此继续轮询。

    这是"扫码成功却拿不到 token"的根因修复：超时被当错误会永久卡住。
    """
    import httpx

    from app.channels import wxclaw_login

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            raise httpx.ReadTimeout("simulated long-poll timeout")

    monkeypatch.setattr(wxclaw_login.httpx, "AsyncClient", FakeClient)
    res = await wxclaw_login.check_login_status("someticket", timeout=0.1)
    assert res == {}


def test_wxclaw_poll_loop_stops_on_token(monkeypatch):
    """后台轮询循环：命中 token 后写入 state 并停止。"""
    import asyncio

    from app.api.v1 import channels as chmod
    import app.channels.wxclaw_login as wl

    calls = {"n": 0}

    async def fake_check(ticket, **kw):
        calls["n"] += 1
        if calls["n"] >= 2:
            return {"token": "TOK", "bot_id": "B1"}
        return {}  # 首次无变化

    monkeypatch.setattr(wl, "check_login_status", fake_check)

    state = {"ticket": "t1", "status": "wait", "token": ""}
    asyncio.new_event_loop().run_until_complete(chmod._wxclaw_poll_loop("k1", state))
    assert state["status"] == "logged_in"
    assert state["token"] == "TOK"
    assert calls["n"] == 2
