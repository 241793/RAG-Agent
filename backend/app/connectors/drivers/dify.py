"""Dify 数据集检索连接器。

配置：base_url（如 https://api.dify.ai/v1 或自建）、api_key（dataset API key）、
      dataset_id、search_method（semantic/full_text/hybrid，默认 semantic）。
接口：POST {base_url}/datasets/{dataset_id}/retrieve
"""
from __future__ import annotations

import httpx

from app.connectors.base import ConnectorDoc
from app.connectors.http_guard import assert_safe_url
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth


class DifyConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15) -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        base = (self.cfg.get("base_url") or "").rstrip("/")
        if not base or not self.cfg.get("dataset_id"):
            raise ValidationError("Dify 连接器需配置 base_url 与 dataset_id")
        self.base_url = base

    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]:
        url = f"{self.base_url}/datasets/{self.cfg['dataset_id']}/retrieve"
        assert_safe_url(url)
        body = {
            "query": query,
            "retrieval_model": {
                "search_method": self.cfg.get("search_method", "semantic_search"),
                "top_k": top_k,
                "score_threshold_enabled": False,
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {self.cfg['api_key']}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        out: list[ConnectorDoc] = []
        for i, rec in enumerate(data.get("records") or []):
            seg = rec.get("segment") or {}
            content = seg.get("content") or ""
            if not content:
                continue
            doc = seg.get("document") or {}
            out.append(
                ConnectorDoc(
                    content=content,
                    title=doc.get("name"),
                    score=float(rec.get("score") or 0.0),
                    source_uri=doc.get("url"),
                    ref=f"kb{self.kb_id}:dify:{seg.get('id') or i}",
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
