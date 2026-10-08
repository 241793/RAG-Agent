"""飞书电子表格连接器：把飞书多维表格/电子表格当检索知识源。

支持两种：
- bitable（多维表格 Bitable）：按记录做关键词检索
- sheet（电子表格）：读一个 sheet 的行

配置（connector_config）：
  mode          bitable（默认）| sheet
  app_id        飞书自建应用 app_id
  app_secret    飞书自建应用 app_secret
  base_token    bitable：多维表格 app_token；sheet：电子表格 spreadsheet_token
  table_id      bitable：数据表 id
  sheet_id      sheet：工作表 id（如 0b12ab）
  search_cols   参与拼接/匹配的列名（逗号分隔；空=全部）
  title_col     作为标题的列名（可选）
  url_col       作为原文链接的列名（可选）

检索策略：拉取表数据（缓存短时）后在本地做关键词匹配（飞书无服务端全文检索），
取包含任一查询词的行，拼成「列名: 值」文本。
"""
from __future__ import annotations

import time

import httpx

from app.connectors.base import ConnectorDoc
from app.connectors.http_guard import assert_safe_url
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

OPEN_API = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{OPEN_API}/auth/v3/tenant_access_token/internal"


def _cell_text(v) -> str:
    """飞书单元格值 → 文本（链接/人员/多选等都是结构化对象）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, list):
        return " ".join(_cell_text(x) for x in v)
    if isinstance(v, dict):
        for k in ("text", "name", "link", "value"):
            if k in v:
                return _cell_text(v[k])
        return " ".join(_cell_text(x) for x in v.values())
    return str(v)


class FeishuSheetConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15) -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        self.mode = (self.cfg.get("mode") or "bitable").lower()
        self.app_id = str(self.cfg.get("app_id") or "")
        self.app_secret = str(self.cfg.get("app_secret") or "")
        self.base_token = str(self.cfg.get("base_token") or "")
        if not (self.app_id and self.app_secret and self.base_token):
            raise ValidationError("飞书表格连接器需配置 app_id / app_secret / base_token")
        if self.mode == "bitable" and not self.cfg.get("table_id"):
            raise ValidationError("bitable 模式需配置 table_id")
        if self.mode == "sheet" and not self.cfg.get("sheet_id"):
            raise ValidationError("sheet 模式需配置 sheet_id")
        self.search_cols = [c.strip() for c in (self.cfg.get("search_cols") or "").split(",") if c.strip()]
        self.title_col = (self.cfg.get("title_col") or "").strip() or None
        self.url_col = (self.cfg.get("url_col") or "").strip() or None
        self._token: str | None = None
        self._cache: list[dict] | None = None
        self._cache_at = 0.0

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if self._token and getattr(self, "_token_at", 0) > time.time() - 600:
            return self._token
        r = await client.post(TOKEN_URL, json={"app_id": self.app_id, "app_secret": self.app_secret})
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {d.get('msg')}")
        self._token = d["tenant_access_token"]
        self._token_at = time.time()
        return self._token

    async def _fetch_rows(self, client: httpx.AsyncClient) -> list[dict]:
        """拉取表数据 → [{列名: 文本值}]。带 60s 内存缓存。"""
        if self._cache is not None and time.time() - self._cache_at < 60:
            return self._cache
        token = await self._get_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        rows: list[dict] = []
        if self.mode == "bitable":
            url = f"{OPEN_API}/bitable/v1/apps/{self.base_token}/tables/{self.cfg['table_id']}/records"
            assert_safe_url(url)
            r = await client.get(url, headers=headers, params={"page_size": 500})
            d = r.json()
            if d.get("code") != 0:
                raise RuntimeError(f"读取多维表格失败: {d.get('msg')}")
            for rec in (d.get("data", {}).get("items") or []):
                fields = rec.get("fields") or {}
                rows.append({k: _cell_text(v) for k, v in fields.items()})
        else:
            # 电子表格：读 A1 区域（默认读前 500 行）
            url = f"{OPEN_API}/sheets/v2/spreadsheets/{self.base_token}/values/{self.cfg['sheet_id']}!A1:Z500"
            assert_safe_url(url)
            r = await client.get(url, headers=headers)
            d = r.json()
            if d.get("code") != 0:
                raise RuntimeError(f"读取电子表格失败: {d.get('msg')}")
            values = (d.get("data", {}).get("valueRange", {}).get("values") or [])
            if values:
                header = [_cell_text(c) for c in values[0]]
                for row in values[1:]:
                    cells = [_cell_text(c) for c in row]
                    rows.append({header[i] if i < len(header) else f"col{i}": (cells[i] if i < len(cells) else "")
                                 for i in range(max(len(header), len(cells)))})
        self._cache = rows
        self._cache_at = time.time()
        return rows

    async def search(self, query: str, *, top_k: int) -> list[ConnectorDoc]:
        assert_safe_url(OPEN_API)
        terms = [t for t in query.split() if t] or [query]
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            rows = await self._fetch_rows(client)
        out: list[ConnectorDoc] = []
        for i, row in enumerate(rows):
            cols = self.search_cols or list(row.keys())
            hay = " ".join(str(row.get(c, "")) for c in cols)
            if not any(t.lower() in hay.lower() for t in terms):
                continue
            parts = [f"{c}: {row.get(c)}" for c in cols if row.get(c)]
            content = "\n".join(parts)
            if not content:
                continue
            out.append(ConnectorDoc(
                content=content,
                title=str(row.get(self.title_col)) if self.title_col and row.get(self.title_col) else None,
                score=0.0,
                source_uri=str(row.get(self.url_col)) if self.url_col and row.get(self.url_col) else None,
                ref=f"kb{self.kb_id}:feishu:{i}",
            ))
            if len(out) >= top_k:
                break
        return out

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            assert_safe_url(OPEN_API)
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                rows = await self._fetch_rows(client)
            return ProviderHealth(ok=True, message=f"连接正常（读到 {len(rows)} 行）",
                                  latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
