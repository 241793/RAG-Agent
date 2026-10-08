"""外部 IM 渠道抽象 —— 与 connectors/ 同风格（dataclass + Protocol）。

入站统一产出 InboundMessage，出站统一用 OutboundMessage；
渠道差异只在 drivers/ 的传输层，业务侧只认这两个结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.providers.base import ProviderHealth


@dataclass
class InboundMessage:
    channel: str                     # qqbot/wxclaw/wework/feishu
    external_user: str               # 渠道内唯一用户标识（openid/unionid/userid）
    content: str
    external_group: str | None = None   # 群聊时的群 id
    is_group: bool = False
    message_id: str | None = None
    display_name: str | None = None
    account: str | None = None       # 多账号场景的账号名
    raw: dict = field(default_factory=dict)
    # 入站媒体附件。每项：
    #   {type: image|file, name, mime, data: bytes|None, url: str|None, aes_key: str|None,
    #    headers: dict|None, feishu_kind: str|None}
    # data 有值则直接用；否则由 media.download_media 按 url/aes_key 下载解密。
    attachments: list[dict] = field(default_factory=list)


@dataclass
class OutboundMessage:
    content: str = ""
    user_id: str | None = None       # 私聊目标（external id）
    group_id: str | None = None      # 群聊目标
    content_type: str = "text"       # text/markdown/image/file
    account: str | None = None
    reply_to: str | None = None      # 部分渠道需回填的消息 id
    # 出站媒体：每项 {type: image|file, name, data: bytes|None, path: str|None}
    media: list[dict] = field(default_factory=list)


@runtime_checkable
class ChannelAdapter(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_message(self, msg: OutboundMessage) -> bool: ...

    async def health(self) -> ProviderHealth: ...
