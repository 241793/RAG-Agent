"""MCP 连接器：通过 JSON-RPC 2.0 调用外部 MCP knowledge server 的检索工具。

最简 HTTP 形态：POST {base_url}  body 为 JSON-RPC。
  {"jsonrpc":"2.0","id":1,"method":"tools/call",
   "params":{"name":"<tool_name>","arguments":{"query":...,"top_k":...}}}
配置：base_url、tool_name（默认 "search"）、api_key、args_template（可选，覆盖默认 arguments）。

响应兼容两种：
  1) {"result":{"content":[{"type":"text","text":"..."}],"structuredContent":{...}}}
  2) {"result":[{...}]} 或 {"result":{"results":[...]}}
命中归一化：优先 structuredContent.results / content[].text（JSON 串）中的数组。
"""
from __future__ import annotations

import json

import httpx

from app.connectors.base import ConnectorDoc
from app.connectors.http_guard import assert_safe_url
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth


class McpConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15) -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        base = (self.cfg.get("base_url") or "").rstrip("/")
        if not base:
            raise ValidationError("MCP 连接器缺少 base_url")
        self.base_url = base
        self.tool_name = self.cfg.get("tool_name") or "search"

    def _arguments(self, query: str, top_k: int) -> dict:
        tpl = self.cfg.get("args_template")
        if tpl:
            raw = json.dumps(tpl, ensure_ascii=False)
            raw = raw.replace("{query}", query).replace("{top_k}", str(top_k))
            return json.loads(raw)
        return {"query": query, "top_k": top_k}

    def _extract_docs(self, result) -> list[dict]:
        """从 MCP 返回结构中尽力提取记录数组。"""
        if isinstance(result, list):
            return result
        if not isinstance(result, dict):
            return []
        for key in ("results", "documents", "items", "matches", "hits"):
            if isinstance(result.get(key), list):
                return result[key]
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            for key in ("results", "documents", "items"):
                if isinstance(sc.get(key), list):
                    return sc[key]
        # 退回解析 content[].text（可能是 JSON 串）
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                try:
                    parsed = json.loads(block.get("text") or "")
                except (json.JSONDecodeError, TypeError):
                    continue
                docs = self._extract_docs(parsed)
                if docs:
                    return docs
        return []

    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]:
        assert_safe_url(self.base_url)
        body = {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": self.tool_name, "arguments": self._arguments(query, top_k)},
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {self.cfg['api_key']}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(self.base_url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValidationError(f"MCP 工具调用失败: {str(data['error'])[:200]}")
        records = self._extract_docs(data.get("result"))
        out: list[ConnectorDoc] = []
        for i, rec in enumerate(records):
            content = rec.get("content") or rec.get("text") or rec.get("snippet") or ""
            if not content:
                continue
            out.append(
                ConnectorDoc(
                    content=str(content),
                    title=rec.get("title") or rec.get("name"),
                    score=float(rec.get("score") or 0.0),
                    page=rec.get("page") if isinstance(rec.get("page"), int) else None,
                    source_uri=rec.get("url") or rec.get("uri"),
                    ref=f"kb{self.kb_id}:mcp:{rec.get('id') or i}",
                )
            )
        return out[:top_k]

    async def health(self) -> ProviderHealth:
        import time

        t0 = time.time()
        try:
            await self.search("健康检查", top_k=1)
            return ProviderHealth(ok=True, message="连接正常", latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
