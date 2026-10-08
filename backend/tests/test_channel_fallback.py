"""渠道回发兜底：指定 channel_id 失效时按 kind 找到运行中的渠道重试。"""
from __future__ import annotations

import asyncio

from app.channels.base import OutboundMessage


class FakeAdapter:
    def __init__(self, kind): self.kind = kind; self.sent = []
    async def send_message(self, m): self.sent.append(m); return True


def test_send_with_fallback_uses_id_when_running():
    from app.channels.manager import ChannelManager

    m = ChannelManager()
    a = FakeAdapter("wxclaw")
    m._adapters[18] = a; m._kinds[18] = "wxclaw"

    async def _run():
        return await m.send_with_fallback(18, "wxclaw", OutboundMessage(content="hi", user_id="u1"))

    assert asyncio.new_event_loop().run_until_complete(_run()) is True
    assert a.sent and a.sent[0].content == "hi"


def test_send_with_fallback_by_kind_when_id_stale():
    """指定 id(17) 已失效，但同 kind 的 18 在运行 → 兜底到 18。"""
    from app.channels.manager import ChannelManager

    m = ChannelManager()
    a = FakeAdapter("wxclaw")
    m._adapters[18] = a; m._kinds[18] = "wxclaw"

    async def _run():
        return await m.send_with_fallback(17, "wxclaw", OutboundMessage(content="hello", user_id="u9"))

    assert asyncio.new_event_loop().run_until_complete(_run()) is True
    assert a.sent and a.sent[0].user_id == "u9"


def test_send_with_fallback_no_match():
    from app.channels.manager import ChannelManager

    m = ChannelManager()

    async def _run():
        return await m.send_with_fallback(99, "feishu", OutboundMessage(content="x", user_id="u"))

    assert asyncio.new_event_loop().run_until_complete(_run()) is False
    assert m.find_running_by_kind("feishu") is None


def test_find_running_by_kind():
    from app.channels.manager import ChannelManager

    m = ChannelManager()
    m._adapters[5] = FakeAdapter("wework"); m._kinds[5] = "wework"
    m._adapters[6] = FakeAdapter("feishu"); m._kinds[6] = "feishu"
    assert m.find_running_by_kind("feishu") == 6
    assert m.find_running_by_kind("wxclaw") is None
