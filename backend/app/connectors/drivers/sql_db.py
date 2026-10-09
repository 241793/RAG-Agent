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


def _strip_sql_comments(sql: str) -> str:
    """去掉 SQL 注释，防止用注释绕过关键字检查（如 /*insert*/、-- insert）。"""
    import re

    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)  # 块注释
    s = re.sub(r"--[^\n]*", " ", s)                   # 行注释
    return s


def _check_readonly(sql: str) -> None:
    """只读校验：必须单条 SELECT/WITH，且不含写关键字。

    加固点：先去注释再判前缀与关键字，避免 `/*x*/insert` 之类绕过；
    并要求整条语句只有一个分号结尾（防多语句堆叠）。
    """
    cleaned = _strip_sql_comments(sql).strip()
    low = cleaned.lower().lstrip("(").strip()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValidationError("SQL 连接器只允许 SELECT/WITH 查询")
    # 防多语句：去掉末尾分号后不应再有分号
    body = cleaned.rstrip().rstrip(";").strip()
    if ";" in body:
        raise ValidationError("只允许单条查询语句（禁止多语句）")
    flat = f" {body.lower()} "
    for kw in _FORBIDDEN:
        if f" {kw} " in flat or f"({kw} " in flat:
            raise ValidationError(f"查询包含被禁止的关键字：{kw}")


def _escape_like(s: str) -> str:
    """转义 LIKE 通配符，避免检索词里的 % / _ 被当作通配（不改变参数绑定语义）。"""
    return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        # 禁止 {query} 字符串拼接占位符（注入面）：检索词必须用 :query 参数绑定
        if "{query}" in self.query_sql:
            raise ValidationError(
                "query_sql 不允许使用 {query} 占位符（存在 SQL 注入风险）；"
                "请改用参数绑定 :query，例如 WHERE name LIKE :query"
            )
        _check_readonly(self.query_sql)
        self.columns = [c.strip() for c in (self.cfg.get("columns") or "").split(",") if c.strip()]
        self.title_col = (self.cfg.get("title_col") or "").strip() or None
        self.url_col = (self.cfg.get("url_col") or "").strip() or None

    def _run(self, query: str, top_k: int, *, sql_override: str | None = None) -> list[ConnectorDoc]:
        """同步执行查询（在线程中调用）。sql_override 用于批量列举。

        安全：检索词一律经参数绑定（:query），绝不字符串拼接进 SQL——
        避免知识库管理员误用 `{query}` 占位导致的注入面。
        """
        from sqlalchemy import create_engine, text

        if sql_override is not None:
            sql = sql_override.replace("{top_k}", str(int(top_k)))
            params: dict = {}
        else:
            sql = self.query_sql.replace("{top_k}", str(int(top_k)))
            params = {}
            # 检索词只走 :query 参数绑定；{query} 拼接占位符已在 __init__ 拒绝
            if ":query" in sql:
                params["query"] = f"%{_escape_like(query)}%"  # 供 LIKE :query 使用
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

    async def list_documents(self, *, limit: int = 500) -> list[ConnectorDoc]:
        """批量列举：用 list_sql（若配置），否则用 query_sql 把 {query} 换成 LIKE 通配 %。"""
        import asyncio

        sql = self.cfg.get("list_sql")
        if sql:
            _check_readonly(sql)
            override = sql
        else:
            override = self.query_sql.replace("{query}", "%")
        return await asyncio.wait_for(
            asyncio.to_thread(self._run, "%", limit, sql_override=override), timeout=self.timeout + 15
        )

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            docs = await self.search("test", top_k=1)
            return ProviderHealth(ok=True, message=f"连接正常（示例命中 {len(docs)} 条）",
                                  latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
