"""Google Sheets 连接器：把 Google 表格当检索知识源。

策略：用「导出为 CSV」的公开端点读取（表格需设为「知道链接的人可查看」）；
私有表可用 api_key（Google API Key）+ 表格公开读取权限。

配置（connector_config）：
  spreadsheet_id  必填，表格 id（URL 中 /d/<id>/ 部分）
  gid             工作表 gid（默认 0）
  api_key         可选，Google API Key
  search_cols     参与匹配/拼接的列名（逗号分隔；空=全部）
  title_col       标题列（可选）
  url_col         原文链接列（可选）
"""
from __future__ import annotations

import csv
import io
import time

import httpx

from app.connectors.base import ConnectorDoc
from app.connectors.http_guard import assert_safe_url
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

EXPORT_CSV = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/A1:Z500?key={key}"


class GoogleSheetConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15) -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        self.sid = str(self.cfg.get("spreadsheet_id") or "").strip()
        if not self.sid:
            raise ValidationError("Google Sheets 连接器需配置 spreadsheet_id")
        self.gid = str(self.cfg.get("gid") or "0")
        self.api_key = (self.cfg.get("api_key") or "").strip()
        self.search_cols = [c.strip() for c in (self.cfg.get("search_cols") or "").split(",") if c.strip()]
        self.title_col = (self.cfg.get("title_col") or "").strip() or None
        self.url_col = (self.cfg.get("url_col") or "").strip() or None
        self._cache: list[dict] | None = None
        self._cache_at = 0.0

    async def _fetch_rows(self, client: httpx.AsyncClient) -> list[dict]:
        if self._cache is not None and time.time() - self._cache_at < 60:
            return self._cache
        rows: list[dict] = []
        if self.api_key:
            url = SHEETS_API.format(sid=self.sid, key=self.api_key)
            assert_safe_url(url)
            r = await client.get(url)
            d = r.json()
            values = d.get("values") or []
            if values:
                header = [str(c) for c in values[0]]
                for row in values[1:]:
                    rows.append({header[i] if i < len(header) else f"col{i}":
                                 (str(row[i]) if i < len(row) else "") for i in range(max(len(header), len(row)))})
        else:
            url = EXPORT_CSV.format(sid=self.sid, gid=self.gid)
            assert_safe_url(url)
            r = await client.get(url)
            r.raise_for_status()
            reader = csv.reader(io.StringIO(r.text))
            data = list(reader)
            if data:
                header = data[0]
                for row in data[1:]:
                    rows.append({header[i] if i < len(header) else f"col{i}":
                                 (row[i] if i < len(row) else "") for i in range(max(len(header), len(row)))})
        self._cache = rows
        self._cache_at = time.time()
        return rows

    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]:
        terms = [t for t in query.split() if t] or [query]
        url = SHEETS_API.format(sid=self.sid, key=self.api_key or "x") if self.api_key else EXPORT_CSV.format(sid=self.sid, gid=self.gid)
        assert_safe_url(url)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            rows = await self._fetch_rows(client)
        out: list[ConnectorDoc] = []
        for i, row in enumerate(rows):
            cols = self.search_cols or list(row.keys())
            hay = " ".join(str(row.get(c, "")) for c in cols)
            if not any(t.lower() in hay.lower() for t in terms):
                continue
            content = "\n".join(f"{c}: {row.get(c)}" for c in cols if row.get(c))
            if not content:
                continue
            out.append(ConnectorDoc(
                content=content,
                title=str(row.get(self.title_col)) if self.title_col and row.get(self.title_col) else None,
                score=0.0,
                source_uri=str(row.get(self.url_col)) if self.url_col and row.get(self.url_col) else None,
                ref=f"kb{self.kb_id}:gsheet:{i}",
            ))
            if len(out) >= top_k:
                break
        return out

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            url = SHEETS_API.format(sid=self.sid, key=self.api_key or "x") if self.api_key else EXPORT_CSV.format(sid=self.sid, gid=self.gid)
            assert_safe_url(url)
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                rows = await self._fetch_rows(client)
            return ProviderHealth(ok=True, message=f"连接正常（读到 {len(rows)} 行）",
                                  latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
