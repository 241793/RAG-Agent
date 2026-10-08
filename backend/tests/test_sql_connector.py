"""SQL 数据库连接器：只读守卫、查询映射、真实 sqlite 检索。"""
from __future__ import annotations

import asyncio

import pytest

from app.connectors.drivers.sql_db import SqlConnector, _check_readonly
from app.core.errors import ValidationError


def test_readonly_guard_allows_select():
    _check_readonly("SELECT * FROM t")
    _check_readonly("WITH x AS (SELECT 1) SELECT * FROM x")
    _check_readonly("  select a,b from t where c like :query")


def test_readonly_guard_blocks_writes():
    for bad in ("DELETE FROM t", "UPDATE t SET a=1", "INSERT INTO t VALUES(1)",
                "DROP TABLE t", "TRUNCATE t", "SELECT 1; DROP TABLE t", "ALTER TABLE t ADD c int"):
        with pytest.raises(ValidationError):
            _check_readonly(bad)


def test_missing_config():
    with pytest.raises(ValidationError):
        SqlConnector(kb_id=1, config={})
    with pytest.raises(ValidationError):
        SqlConnector(kb_id=1, config={"dsn": "sqlite:///:memory:"})
    with pytest.raises(ValidationError):
        SqlConnector(kb_id=1, config={"dsn": "sqlite:///:memory:", "query_sql": "DROP TABLE t"})


def test_sql_search_real(tmp_path):
    """真实 sqlite 库：建表插数据 → 检索映射。"""
    dsn = f"sqlite:///{(tmp_path / 'kb.db').as_posix()}"
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "kb.db"))
    conn.execute("CREATE TABLE faq (question TEXT, answer TEXT, url TEXT)")
    conn.executemany("INSERT INTO faq VALUES (?,?,?)", [
        ("如何请假", "在 OA 提交申请", "https://oa/leave"),
        ("报销流程", "填写报销单交财务", "https://oa/reimburse"),
        ("年假天数", "工作满一年 5 天", "https://oa/annual"),
    ])
    conn.commit(); conn.close()

    c = SqlConnector(kb_id=7, config={
        "dsn": dsn,
        "query_sql": "SELECT question, answer, url FROM faq WHERE question LIKE :query OR answer LIKE :query LIMIT {top_k}",
        "columns": "question,answer", "title_col": "question", "url_col": "url",
    })
    docs = asyncio.new_event_loop().run_until_complete(c.search("报销", top_k=5))
    assert len(docs) == 1
    d = docs[0]
    assert "报销流程" in d.content and "填写报销单交财务" in d.content
    assert d.title == "报销流程"
    assert d.source_uri == "https://oa/reimburse"
    assert d.ref == "kb7:sql:0"


def test_sql_health(tmp_path):
    import sqlite3
    dsn = f"sqlite:///{(tmp_path / 'h.db').as_posix()}"
    conn = sqlite3.connect(str(tmp_path / "h.db"))
    conn.execute("CREATE TABLE t (a TEXT)"); conn.execute("INSERT INTO t VALUES ('x')")
    conn.commit(); conn.close()
    c = SqlConnector(kb_id=1, config={"dsn": dsn, "query_sql": "SELECT a FROM t"})
    h = asyncio.new_event_loop().run_until_complete(c.health())
    assert h.ok is True


def test_sql_health_bad_dsn():
    c = SqlConnector(kb_id=1, config={"dsn": "sqlite:///./nonexistent_dir_xyz/x.db",
                                      "query_sql": "SELECT 1"})
    h = asyncio.new_event_loop().run_until_complete(c.health())
    assert h.ok is False


def test_registry_builds_sql_connector():
    from app.connectors.registry import build_connector

    c = build_connector("sql_db", {"dsn": "sqlite:///:memory:", "query_sql": "SELECT 1"})
    assert isinstance(c, SqlConnector)
