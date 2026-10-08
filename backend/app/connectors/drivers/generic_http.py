"""通用 HTTP 连接器：任何返回 JSON 的 REST 检索接口都能接。

配置（connector_config）：
  base_url          必填，检索接口基址（如 https://api.example.com）
  search_path       追加到 base_url 的路径，可含 {query}/{top_k} 占位
  method            GET / POST（默认 POST）
  headers           dict，值可含 {query}
  request_template  POST body 模板（dict/list/str），字符串值中的 {query}/{top_k} 会被替换
  query_param       GET 时承载 query 的参数名（默认 "q"）
  top_k_param       GET 时承载 top_k 的参数名（可选）
  response_list_path  点路径，定位结果数组（如 "data.records"；留空则响应根即数组）
  content_path     每条内的内容字段点路径（默认 "content"）
  title_path       标题点路径（可选）
  score_path       分数点路径（可选）
  page_path        页码点路径（可选）
  url_path         原文链接点路径（可选）
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.connectors.base import ConnectorDoc
from app.connectors.http_guard import assert_safe_url
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth


def _dig(obj: Any, path: str | None) -> Any:
    """按点路径取值；空路径返回原对象。路径不存在返回 None。"""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _subst(value: Any, query: str, top_k: int) -> Any:
    """递归替换模板中的 {query}/{top_k}。"""
    if isinstance(value, str):
        return value.replace("{query}", query).replace("{top_k}", str(top_k))
    if isinstance(value, dict):
        return {k: _subst(v, query, top_k) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, query, top_k) for v in value]
    return value


def map_records(payload: Any, cfg: dict, *, kb_id: int) -> list[ConnectorDoc]:
    """把响应 payload 按点路径映射成 ConnectorDoc 列表（纯函数，便于测试）。"""
    records = _dig(payload, cfg.get("response_list_path"))
    if records is None:
        records = []
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise ValidationError("response_list_path 未定位到数组，请检查响应映射配置")

    out: list[ConnectorDoc] = []
    for i, rec in enumerate(records):
        content = _dig(rec, cfg.get("content_path", "content"))
        if content is None:
            continue
        title = _dig(rec, cfg.get("title_path")) if cfg.get("title_path") else None
        score = _dig(rec, cfg.get("score_path")) if cfg.get("score_path") else None
        page = _dig(rec, cfg.get("page_path")) if cfg.get("page_path") else None
        url = _dig(rec, cfg.get("url_path")) if cfg.get("url_path") else None
        out.append(
            ConnectorDoc(
                content=str(content),
                title=str(title) if title is not None else None,
                score=float(score) if isinstance(score, (int, float)) else 0.0,
                page=int(page) if isinstance(page, (int, float)) else None,
                source_uri=str(url) if url else None,
                ref=f"kb{kb_id}:{i}",
            )
        )
    return out


class GenericHttpConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15) -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        base = (self.cfg.get("base_url") or "").rstrip("/")
        if not base:
            raise ValidationError("通用 HTTP 连接器缺少 base_url")
        self.base_url = base

    def _request_args(self, query: str, top_k: int) -> tuple[str, str, dict, dict | None, dict]:
        method = (self.cfg.get("method") or "POST").upper()
        path = _subst(self.cfg.get("search_path") or "", query, top_k)
        url = self.base_url + (path if path.startswith("/") or not path else f"/{path}")
        headers = {k: _subst(str(v), query, top_k) for k, v in (self.cfg.get("headers") or {}).items()}
        api_key = self.cfg.get("api_key")
        if api_key:
            headers.setdefault("Authorization", f"Bearer {api_key}")
        params: dict = {}
        body = None
        if method == "GET":
            params[self.cfg.get("query_param", "q")] = query
            if self.cfg.get("top_k_param"):
                params[self.cfg["top_k_param"]] = top_k
        else:
            body = _subst(self.cfg.get("request_template") or {"query": "{query}", "top_k": "{top_k}"}, query, top_k)
        return method, url, headers, body, params

    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]:
        method, url, headers, body, params = self._request_args(query, top_k)
        assert_safe_url(url)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            else:
                resp = await client.post(url, headers={**headers, "Content-Type": "application/json"},
                                         content=json.dumps(body, ensure_ascii=False))
        resp.raise_for_status()
        payload = resp.json()
        return map_records(payload, self.cfg, kb_id=self.kb_id)[:top_k]

    async def health(self) -> ProviderHealth:
        import time

        t0 = time.time()
        try:
            await self.search("健康检查", top_k=1)
            return ProviderHealth(ok=True, message="连接正常", latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
