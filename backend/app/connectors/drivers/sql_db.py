"""SQL 数据库连接器：把数据库表/视图当检索知识源。

思路：用一条带 :query 占位（或 {query} 替换）的 SELECT 语句做关键词检索，
把每行按「列名: 值」拼成可读文本作为知识片段。

配置（connector_config）：
  dsn        必填，SQLAlchemy 同步连接串，如
             sqlite:///./data/other.db  /  postgresql://user:pwd@host/db  /  mysql+pymysql://...
  query_sql  必填，检索 SQL，含 {query} 或 :query 占位；建议 LIMIT {top_k}
  columns    可选，参与拼接的列（逗号分隔；空=全部列）
  title_col  可选，作为标题的列名
  url_col    可选，作为原文链接的列名

安全：
- 只允许 SELECT（拦截写操作），防误改外部库。
- 查询用参数绑定（:query），避免注入；{query}/{top_k} 只做字符串替换但不拼用户可控表名。
- DSN 连接串经 http_guard 类似的私网校验？外部库本身即内网资源，故不拦（与连接器定位一致）。
"""
from __future__ import annotations

import time

from app.connectors.base import ConnectorDoc
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

_FORBIDDEN = ("insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke")


def _check_readonly(sql: str) -> None:
    low = sql.strip().lower().lstrip("(").strip()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValidationError("SQL 连接器只允许 SELECT/WITH 查询")
    flat = sql.lower()
    for kw in _FORBIDDEN:
        if f" {kw} " in f" {flat} ":
            raise ValidationError(f"查询包含被禁止的关键字：{kw}")


class SqlConnector:
    def __init__(self, *, kb_id: int, config: dict, timeout: int = 15) -> None:
        self.kb_id = kb_id
        self.cfg = config or {}
        self.timeout = timeout
        self.dsn = (self.cfg.get("dsn") or "").strip()
        if not self.dsn:
            raise ValidationError("SQL 连接器缺少 dsn")
        self.query_sql = (self.cfg.get("query_sql") or "").strip()
        if not self.query_sql:
            raise ValidationError("SQL 连接器缺少 query_sql")
        _check_readonly(self.query_sql)
        self.columns = [c.strip() for c in (self.cfg.get("columns") or "").split(",") if c.strip()]
        self.title_col = (self.cfg.get("title_col") or "").strip() or None
        self.url_col = (self.cfg.get("url_col") or "").strip() or None

    def _run(self, query: str, top_k: int) -> list[ConnectorDoc]:
        """同步执行查询（在线程中调用）。"""
        from sqlalchemy import create_engine, text

        sql = self.query_sql.replace("{top_k}", str(int(top_k)))
        params: dict = {}
        if ":query" in sql:
            params["query"] = f"%{query}%"  # 供 LIKE :query 使用
        else:
            sql = sql.replace("{query}", query)
        engine = create_engine(self.dsn, pool_pre_ping=True)
        try:
            out: list[ConnectorDoc] = []
            with engine.connect() as conn:
                result = conn.execute(text(sql), params)
                keys = list(result.keys())
                for i, row in enumerate(result):
                    if i >= top_k:
                        break
                    m = dict(zip(keys, row))
                    use_cols = self.columns or keys
                    parts = [f"{c}: {m[c]}" for c in use_cols if c in m and m[c] is not None]
                    content = "\n".join(parts)
                    if not content:
                        continue
                    title = str(m.get(self.title_col)) if self.title_col and m.get(self.title_col) is not None else None
                    url = str(m.get(self.url_col)) if self.url_col and m.get(self.url_col) is not None else None
                    out.append(ConnectorDoc(content=content, title=title, score=0.0,
                                            source_uri=url, ref=f"kb{self.kb_id}:sql:{i}"))
            return out
        finally:
            engine.dispose()

    async def search(self, query: str, *, top_k: int = 5) -> list[ConnectorDoc]:
        import asyncio

        return await asyncio.wait_for(
            asyncio.to_thread(self._run, query, top_k), timeout=self.timeout + 5
        )

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            docs = await self.search("test", top_k=1)
            return ProviderHealth(ok=True, message=f"连接正常（示例命中 {len(docs)} 条）",
                                  latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
