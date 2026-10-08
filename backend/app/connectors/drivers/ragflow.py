"""RAGFlow / FastGPT 连接器。

RAGFlow：POST {base_url}/api/v1/retrieval  body {question, dataset_ids}
         响应 data.chunks[].{content, document_keyword, document_name}
FastGPT：POST {base_url}/core/dataset/searchTest  body {datasetId, text}
         响应 data.list[].{q, a} 或 data（数组）
配置：base_url、api_key、dataset_ids（RAGFlow，列表或逗号串）/ dataset_id（FastGPT）。
"""
from __future__ import annotations

import httpx

from app.connectors.base import ConnectorDoc
from app.connectors.http_guard import assert_safe_url
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth


class RagflowConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15, kind: str = "ragflow") -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        self.kind = kind
        base = (self.cfg.get("base_url") or "").rstrip("/")
        if not base:
            raise ValidationError(f"{kind} 连接器缺少 base_url")
        self.base_url = base

    def _dataset_ids(self) -> list[str]:
        raw = self.cfg.get("dataset_ids") or self.cfg.get("dataset_id") or []
        if isinstance(raw, str):
            return [x.strip() for x in raw.split(",") if x.strip()]
        return list(raw)

    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]:
        if self.kind == "fastgpt":
            return await self._search_fastgpt(query, top_k)
        return await self._search_ragflow(query, top_k)

    async def _search_ragflow(self, query: str, top_k: int) -> list[ConnectorDoc]:
        url = f"{self.base_url}/api/v1/retrieval"
        assert_safe_url(url)
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {self.cfg['api_key']}"
        body = {"question": query, "dataset_ids": self._dataset_ids(), "page_size": top_k}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        chunks = (((data.get("data") or {}).get("chunks")) or [])
        out: list[ConnectorDoc] = []
        for i, c in enumerate(chunks):
            content = c.get("content") or c.get("content_with_weight") or ""
            if not content:
                continue
            out.append(
                ConnectorDoc(
                    content=content,
                    title=c.get("document_keyword") or c.get("document_name"),
                    score=float(c.get("similarity") or c.get("score") or 0.0),
                    ref=f"kb{self.kb_id}:ragflow:{c.get('id') or i}",
                )
            )
        return out[:top_k]

    async def _search_fastgpt(self, query: str, top_k: int) -> list[ConnectorDoc]:
        url = f"{self.base_url}/core/dataset/searchTest"
        assert_safe_url(url)
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {self.cfg['api_key']}"
        body = {"datasetId": self.cfg.get("dataset_id"), "text": query, "limit": top_k}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        inner = data.get("data") or {}
        records = inner.get("list") if isinstance(inner, dict) else inner
        out: list[ConnectorDoc] = []
        for i, r in enumerate(records or []):
            content = r.get("q") or r.get("content") or ""
            if not content:
                continue
            out.append(
                ConnectorDoc(
                    content=content,
                    title=r.get("a") or None,
                    score=float(r.get("score") or 0.0),
                    ref=f"kb{self.kb_id}:fastgpt:{r.get('id') or i}",
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
