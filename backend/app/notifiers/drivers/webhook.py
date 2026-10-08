"""通用 Webhook 通知渠道：POST 一条 JSON 到用户配置的 URL。

config: {url, method(POST), headers(dict), template(dict，含 {title}/{body}/{level})}
出站经 http_guard 做 SSRF 防护，follow_redirects=False。
"""
from __future__ import annotations

import json
import time

import httpx

from app.connectors.http_guard import assert_safe_url
from app.notifiers.base import NotificationMessage
from app.providers.base import ProviderHealth


class WebhookNotifier:
    def __init__(self, *, config: dict | None = None, timeout: int = 10) -> None:
        self.cfg = config or {}
        self.timeout = timeout

    def _body(self, msg: NotificationMessage) -> dict:
        tpl = self.cfg.get("template")
        if tpl:
            raw = json.dumps(tpl, ensure_ascii=False)
            raw = raw.replace("{title}", msg.title).replace("{body}", msg.body or "")
            raw = raw.replace("{level}", msg.level).replace("{kind}", msg.kind)
            return json.loads(raw)
        return {"title": msg.title, "body": msg.body, "level": msg.level, "kind": msg.kind, "link": msg.link}

    async def send(self, msg: NotificationMessage) -> bool:
        url = self.cfg.get("url")
        if not url:
            return False
        assert_safe_url(url)
        headers = {"Content-Type": "application/json", **(self.cfg.get("headers") or {})}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(url, headers=headers, content=json.dumps(self._body(msg), ensure_ascii=False))
        resp.raise_for_status()
        return True

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            url = self.cfg.get("url")
            if not url:
                return ProviderHealth(ok=False, message="未配置 url", latency_ms=0)
            assert_safe_url(url)
            return ProviderHealth(ok=True, message="配置有效", latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
