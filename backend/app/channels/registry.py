"""渠道适配器注册表：按 kind 构建实例（与 connectors/registry.py 同构）。"""
from __future__ import annotations

from app.core.errors import ValidationError


def build_adapter(kind: str, *, config: dict, on_message):
    """按渠道类型构建适配器。config 内的密钥应已解密。"""
    if kind == "qqbot":
        from app.channels.drivers.qqbot import QQBotAdapter

        return QQBotAdapter(config=config, on_message=on_message)
    if kind == "wxclaw":
        from app.channels.drivers.wxclaw import WxClawAdapter

        return WxClawAdapter(config=config, on_message=on_message)
    if kind == "wework":
        from app.channels.drivers.wework import WeWorkAdapter

        return WeWorkAdapter(config=config, on_message=on_message)
    if kind == "feishu":
        from app.channels.drivers.feishu import FeishuAdapter

        return FeishuAdapter(config=config, on_message=on_message)
    raise ValidationError(f"不支持的渠道类型: {kind}")


SUPPORTED_KINDS = ("qqbot", "wxclaw", "wework", "feishu")
