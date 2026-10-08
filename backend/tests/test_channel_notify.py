"""外部渠道复用为通知出口/推送节点：渠道主动发送、external 通知驱动、/myuid 指令、notify 工作流节点。"""
from __future__ import annotations

import asyncio

import pytest

from app.channels.base import OutboundMessage


class _FakeAdapter:
    def __init__(self):
        self.sent: list[OutboundMessage] = []

    async def send_message(self, msg: OutboundMessage) -> bool:
        self.sent.append(msg)
        return True


# ---- channel_manager 主动发送 ----
def test_manager_send_not_ready():
    from app.channels.manager import ChannelManager

    m = ChannelManager()

    async def _run():
        ok = await m.send(999, OutboundMessage(content="x", group_id="g"))
        return ok

    assert asyncio.new_event_loop().run_until_complete(_run()) is False


def test_manager_send_routes_to_adapter():
    from app.channels.manager import ChannelManager

    m = ChannelManager()
    fa = _FakeAdapter()
    m._adapters[7] = fa

    async def _run():
        return await m.send(7, OutboundMessage(content="hi", group_id="g1"))

    ok = asyncio.new_event_loop().run_until_complete(_run())
    assert ok is True
    assert fa.sent and fa.sent[0].group_id == "g1"
    assert m.is_connected(7) is True
    assert m.get_adapter(7) is fa


# ---- external 通知驱动 ----
def test_external_notifier_group_and_user():
    from app.notifiers.drivers.external import ExternalChannelNotifier

    class M:
        title = "标题"
        body = "正文"
        link = "/scheduled"

    n = ExternalChannelNotifier(tenant_id=1, config={"channel_id": 3, "target": "grp", "target_type": "group"})
    out = n._build_out(M())
    assert out.group_id == "grp" and out.user_id is None
    assert "标题" in out.content and "正文" in out.content and "/scheduled" in out.content

    n2 = ExternalChannelNotifier(tenant_id=1, config={"channel_id": 3, "target": "usr", "target_type": "user"})
    out2 = n2._build_out(M())
    assert out2.user_id == "usr" and out2.group_id is None


def test_build_notifier_external():
    from app.notifiers.drivers.external import ExternalChannelNotifier
    from app.notifiers.registry import build_notifier

    n = build_notifier("external", tenant_id=1, config={"channel_id": 1, "target": "t"})
    assert isinstance(n, ExternalChannelNotifier)


def test_external_notifier_send_uses_manager(monkeypatch):
    from app.channels.manager import channel_manager
    from app.notifiers.drivers.external import ExternalChannelNotifier

    captured = {}

    async def _fake_send(channel_id, kind, out):
        captured["channel_id"] = channel_id
        captured["out"] = out
        return True

    monkeypatch.setattr(channel_manager, "send_with_fallback", _fake_send)

    class M:
        title = "T"
        body = "B"
        link = None

    n = ExternalChannelNotifier(tenant_id=1, config={"channel_id": 42, "target": "g", "target_type": "group"})
    ok = asyncio.new_event_loop().run_until_complete(n.send(M()))
    assert ok is True
    assert captured["channel_id"] == 42
    assert captured["out"].group_id == "g"


def test_external_notifier_health():
    from app.channels.manager import channel_manager
    from app.notifiers.drivers.external import ExternalChannelNotifier

    n = ExternalChannelNotifier(tenant_id=1, config={"channel_id": 1, "target": "g"})
    # 未连接 → health ok=False
    h = asyncio.new_event_loop().run_until_complete(n.health())
    assert h.ok is False
    # 缺 target → ok=False 且提示
    n2 = ExternalChannelNotifier(tenant_id=1, config={"channel_id": 1})
    h2 = asyncio.new_event_loop().run_until_complete(n2.health())
    assert h2.ok is False and "接收对象" in h2.message


# ---- /myuid 指令 ----
def test_myuid_private_and_group():
    from app.channels.commands import COMMANDS, HELP_TEXT, CommandContext, cmd_myuid

    assert "myuid" in COMMANDS
    assert "myuid" in HELP_TEXT

    class CU:
        external_id = "openid_123"
        display_name = "张三"

    class Ch:
        name = "测试群机器人"
        kind = "wework"

    async def _run(group):
        ctx = CommandContext(db=None, channel=Ch(), channel_user=CU(), user=None, ps=None, external_group=group)
        return await cmd_myuid(ctx, [])

    loop = asyncio.new_event_loop()
    private = loop.run_until_complete(_run(None))
    assert "openid_123" in private and "群 id" not in private
    group = loop.run_until_complete(_run("group_abc"))
    assert "group_abc" in group and "openid_123" in group


# ---- 工作流 notify 节点 ----
def test_notify_node_registered():
    from app.agents.workflow.engine import NODE_EXECUTORS

    assert "notify" in NODE_EXECUTORS


def test_notify_node_external_channel(monkeypatch):
    from app.agents.workflow.engine import _exec_notify

    from app.channels.manager import channel_manager

    captured = {}

    async def _fake_send(channel_id, kind, out):
        captured["channel_id"] = channel_id
        captured["content"] = out.content
        captured["group_id"] = out.group_id
        return True

    monkeypatch.setattr(channel_manager, "send_with_fallback", _fake_send)

    class Ctx:
        db = None
        tenant_id = 1
        run_id = 5
        ps = type("P", (), {"user_id": 1})()

    node = {"id": "n1", "type": "notify",
            "data": {"mode": "external_channel", "channel_id": 3, "target": "g", "target_type": "group",
                     "content": "hello"}}
    data = {"content": "hello"}
    out = asyncio.new_event_loop().run_until_complete(_exec_notify(node, data, Ctx()))
    assert out["sent"] is True
    assert captured["channel_id"] == 3 and captured["content"] == "hello" and captured["group_id"] == "g"


def test_notify_node_empty_content():
    from app.core.errors import ValidationError
    from app.agents.workflow.engine import _exec_notify

    class Ctx:
        db = None
        tenant_id = 1
        run_id = 5

    node = {"id": "n1", "type": "notify", "data": {"mode": "external_channel", "channel_id": 3, "target": "g"}}
    with pytest.raises(ValidationError):
        asyncio.new_event_loop().run_until_complete(_exec_notify(node, {"content": ""}, Ctx()))
