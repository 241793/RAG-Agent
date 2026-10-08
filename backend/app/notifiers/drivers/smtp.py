"""邮件通知渠道（标准库 smtplib，零新依赖）。

config: {host, port(465/587), username, password, use_ssl(bool), from_addr, to_addrs(list|str)}
"""
from __future__ import annotations

import asyncio
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from app.notifiers.base import NotificationMessage
from app.providers.base import ProviderHealth


class SmtpNotifier:
    def __init__(self, *, config: dict | None = None) -> None:
        self.cfg = config or {}

    def _build_mail(self, msg: NotificationMessage) -> MIMEMultipart:
        mail = MIMEMultipart()
        mail.attach(MIMEText(msg.body or msg.title, "plain", "utf-8"))
        for att in (msg.attachments or []):
            try:
                data = att.get("data") or b""
                part = MIMEApplication(data, Name=att.get("name") or "file")
                part["Content-Disposition"] = f'attachment; filename="{att.get("name") or "file"}"'
                mail.attach(part)
            except Exception:  # noqa: BLE001
                continue
        return mail

    def _send_sync(self, msg: NotificationMessage) -> None:
        cfg = self.cfg
        host = cfg.get("host")
        if not host:
            raise ValueError("SMTP 未配置 host")
        port = int(cfg.get("port") or (465 if cfg.get("use_ssl") else 587))
        to_raw = cfg.get("to_addrs") or []
        to_addrs = [x.strip() for x in to_raw.split(",")] if isinstance(to_raw, str) else list(to_raw)
        if not to_addrs:
            raise ValueError("SMTP 未配置收件人 to_addrs")

        mail = self._build_mail(msg)
        mail["Subject"] = msg.title
        mail["From"] = formataddr(("RAG 知识库", cfg.get("from_addr") or cfg.get("username") or ""))
        mail["To"] = ", ".join(to_addrs)

        if cfg.get("use_ssl"):
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        try:
            if cfg.get("username"):
                server.login(cfg["username"], cfg.get("password") or "")
            server.sendmail(cfg.get("from_addr") or cfg.get("username"), to_addrs, mail.as_string())
        finally:
            server.quit()

    async def send(self, msg: NotificationMessage) -> bool:
        # smtplib 是同步阻塞的，放到线程池避免阻塞事件循环
        await asyncio.to_thread(self._send_sync, msg)
        return True

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        missing = [k for k in ("host", "to_addrs") if not self.cfg.get(k)]
        if missing:
            return ProviderHealth(ok=False, message=f"缺少配置: {', '.join(missing)}", latency_ms=0)
        return ProviderHealth(ok=True, message="配置完整（发送时验证连通）", latency_ms=int((time.time() - t0) * 1000))
