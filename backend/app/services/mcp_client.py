"""MCP 客户端：自研 JSON-RPC 2.0，零新增依赖（httpx + asyncio）。

实现 initialize / tools/list / tools/call，支持三种传输：
- http  ：streamable-http，POST JSON-RPC；响应可为 application/json 或 text/event-stream。
- sse   ：GET 建流收 endpoint，再 POST 到该 endpoint，响应从 SSE 流按 id 配对。
- stdio ：长驻子进程（由 mcp_manager 管理），逐行 JSON-RPC。

安全：http/sse 出站走 assert_safe_url（SSRF 守卫）；stdio 命令白名单由 manager 把关。
"""
from __future__ import annotations

import asyncio
import json
import time

from app.core.errors import ValidationError
from app.core.logging import get_logger

logger = get_logger("mcp_client")

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "rag-knowledge-base", "version": "1.0"}


class McpError(Exception):
    """MCP 调用错误（协议/传输/工具执行）。"""


def _jsonrpc(method: str, params: dict | None, id_: int) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _parse_sse_body(text: str) -> list[dict]:
    """从 SSE 文本里抽取 data: 行的 JSON 对象。"""
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                out.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
    return out


class McpClient:
    """单传输 MCP 客户端。http/sse 无状态；stdio 由外部注入管道。"""

    def __init__(
        self,
        *,
        transport: str,
        url: str | None = None,
        headers: dict | None = None,
        timeout: int = 30,
        stdio=None,  # _StdioChannel | None
    ) -> None:
        self.transport = transport
        self.url = (url or "").rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = timeout
        self._stdio = stdio
        self._seq = 0

    # ---- 底层请求 ----
    async def _post(self, client, target: str, body: dict) -> dict:
        resp = await client.post(
            target,
            json=body,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **self.headers},
        )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for obj in _parse_sse_body(resp.text):
                if obj.get("id") == body["id"]:
                    return obj
            # 单次响应（streamable-http 常见形态）
            objs = _parse_sse_body(resp.text)
            if objs:
                return objs[-1]
            raise McpError("SSE 响应中未找到匹配的 JSON-RPC 结果")
        return resp.json()

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    async def _request(self, method: str, params: dict | None) -> dict:
        """发送一次 JSON-RPC 请求，返回 result（失败抛 McpError）。"""
        body = _jsonrpc(method, params, self._next_id())
        try:
            if self.transport == "stdio":
                if self._stdio is None:
                    raise McpError("stdio 通道未建立")
                data = await self._stdio.request(body, self.timeout)
            else:
                import httpx

                from app.connectors.http_guard import assert_safe_url

                assert_safe_url(self.url)
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                    if self.transport == "sse":
                        data = await self._request_sse(client, body)
                    else:
                        data = await self._post(client, self.url, body)
        except McpError:
            raise
        except Exception as e:  # noqa: BLE001
            raise McpError(f"传输失败：{str(e)[:200]}") from e

        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise McpError(f"MCP 错误：{msg}")
        return (data or {}).get("result") or {}

    async def _request_sse(self, client, body: dict) -> dict:
        """SSE 传输：GET 建流取 endpoint → POST → 从流按 id 配对响应。"""
        from app.connectors.http_guard import assert_safe_url

        # 1) GET 建流，读首条 endpoint 事件
        endpoint_url: str | None = None
        async with client.stream(
            "GET", self.url,
            headers={"Accept": "text/event-stream", **self.headers},
        ) as stream:
            if stream.status_code >= 400:
                raise McpError(f"SSE 建流失败：HTTP {stream.status_code}")
            # 逐行读取，找到 endpoint
            async for line in stream.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    ep = line[5:].strip()
                    if ep:
                        from urllib.parse import urljoin

                        endpoint_url = urljoin(self.url, ep)
                        break
            if not endpoint_url:
                raise McpError("SSE 未返回 endpoint")
            assert_safe_url(endpoint_url)
            # 2) POST 请求体到 endpoint
            resp = await client.post(
                endpoint_url, json=body,
                headers={"Content-Type": "application/json", **self.headers},
            )
            resp.raise_for_status()
            # 3) 从同一 SSE 流继续读，按 id 配对
            async for line in stream.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                try:
                    obj = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if obj.get("id") == body["id"]:
                    return obj
            raise McpError("SSE 未返回匹配的响应")

    # ---- 高层方法 ----
    async def initialize(self) -> dict:
        return await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._request("tools/call", {"name": name, "arguments": arguments or {}})

    async def ping(self) -> bool:
        try:
            await self.initialize()
            return True
        except McpError:
            return False


def content_to_text(result: dict) -> str:
    """把 MCP tools/call 结果归一化为文本。"""
    blocks = result.get("content") if isinstance(result, dict) else None
    if not isinstance(blocks, list):
        # 兼容 structuredContent 或裸对象
        if isinstance(result, dict) and result.get("structuredContent") is not None:
            return json.dumps(result["structuredContent"], ensure_ascii=False)[:65536]
        return json.dumps(result, ensure_ascii=False)[:65536] if result else "(无输出)"
    parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            parts.append(str(b))
            continue
        btype = b.get("type")
        if btype == "text":
            parts.append(str(b.get("text") or ""))
        elif btype in ("image", "audio", "resource"):
            parts.append(f"[{btype}: {b.get('mimeType') or b.get('uri') or ''}]")
        else:
            parts.append(json.dumps(b, ensure_ascii=False))
    return "\n".join(parts)[:65536] or "(无输出)"


async def build_client(server, *, db=None) -> McpClient:
    """从 McpServer 行构造客户端（解密敏感字段；stdio 走 manager 取长驻通道）。"""
    from app.core.crypto import decrypt

    transport = (server.transport or "http").lower()
    headers = dict(server.headers or {})
    # headers 值解密（存的是 enc: 密文）
    for k, v in list(headers.items()):
        if isinstance(v, str) and v.startswith("enc:"):
            headers[k] = decrypt(v)
    token = decrypt(server.auth_token) if server.auth_token else None
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")

    from app.core.config import settings

    timeout = int(server.timeout or settings.mcp_default_timeout)

    if transport == "stdio":
        from app.services.mcp_manager import mcp_manager

        channel = await mcp_manager.get_stdio(server)
        return McpClient(transport="stdio", timeout=timeout, stdio=channel)

    return McpClient(
        transport=transport, url=server.url, headers=headers, timeout=timeout,
    )
