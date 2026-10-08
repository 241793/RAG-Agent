"""外部连接器的出站 URL 安全守卫（SSRF 防护）。

base_url 由用户配置，属不可信输入。放行前必须：
1. 只允许 http/https；
2. 解析 host 的全部 IP（防 DNS 指向内网）；
3. 拒绝私网/环回/链路本地/保留地址段（除非 settings.connector_allow_private）；
4. 出站请求统一 follow_redirects=False，防重定向绕过。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.errors import ValidationError


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_safe_url(url: str, *, allow_private: bool | None = None) -> None:
    """校验 URL 是否可安全出站。不通过抛 ValidationError。"""
    from app.core.config import settings

    if allow_private is None:
        allow_private = settings.connector_allow_private

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError(f"仅支持 http/https，收到: {parsed.scheme or '(空)'}")
    host = parsed.hostname
    if not host:
        raise ValidationError("URL 缺少主机名")

    if allow_private:
        return

    # 解析全部 A/AAAA 记录并逐一校验（防 DNS 轮询绕过）
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValidationError(f"无法解析主机名 {host}: {e}") from e

    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise ValidationError(
                f"出于安全考虑，禁止外部知识库指向内网/保留地址（{host} → {ip}）。"
                f"如为企业内网部署，请设置环境变量 CONNECTOR_ALLOW_PRIVATE=true 后重启。"
            )
