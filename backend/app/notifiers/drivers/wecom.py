"""企业微信 / 钉钉群机器人通知渠道（markdown 卡片）。

企微：POST {webhook_url}  body {"msgtype":"markdown","markdown":{"content":"..."}}
钉钉：POST {webhook_url}  body {"msgtype":"markdown","markdown":{"title":"...","text":"..."}}
  (钉钉含加签场景：secret 时需在 URL 追加 timestamp+sign)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

import httpx

from app.connectors.http_guard import assert_safe_url
from app.notifiers.base import NotificationMessage
from app.providers.base import ProviderHealth

_LEVEL_EMOJI = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}


class WecomNotifier:
    def __init__(self, *, config: dict | None = None, timeout: int = 10, kind: str = "wecom") -> None:
        self.cfg = config or {}
        self.timeout = timeout
        self.kind = kind

    def _url(self) -> str:
        url = self.cfg.get("webhook_url") or ""
        if self.kind == "dingtalk" and self.cfg.get("secret") and url:
            ts = str(round(time.time() * 1000))
            string_to_sign = f"{ts}\n{self.cfg['secret']}"
            sign = base64.b64encode(
                hmac.new(self.cfg["secret"].encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
            )
            sign = urllib.parse.quote_plus(sign)
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}timestamp={ts}&sign={sign}"
        return url

    def _content(self, msg: NotificationMessage) -> str:
        emoji = _LEVEL_EMOJI.get(msg.level, "")
        lines = [f"### {emoji} {msg.title}"]
        if msg.body:
            lines.append(msg.body)
        if msg.link:
            lines.append(f"[查看详情]({msg.link})")
        return "\n".join(lines)

    async def send(self, msg: NotificationMessage) -> bool:
        url = self._url()
        if not url:
            return False
        assert_safe_url(url)
        body = {"msgtype": "markdown", "markdown": {"content": self._content(msg)}}
        if self.kind == "dingtalk":
            body["markdown"]["title"] = msg.title
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(url, json=body)
        resp.raise_for_status()
        return True

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            url = self._url()
            if not url:
                return ProviderHealth(ok=False, message="未配置 webhook_url", latency_ms=0)
            assert_safe_url(url)
            return ProviderHealth(ok=True, message="配置有效", latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
