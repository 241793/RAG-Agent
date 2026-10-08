"""系统运维接口测试：信息、切库向导（测试连接/装驱动白名单/建表）、备份还原、初始化、清理、
切库崩溃兜底回退。仅用 SQLite 与临时文件，不依赖真实 PG/MySQL。"""
from __future__ import annotations

import asyncio
import json

from app.core.config import DATA_DIR, settings
from app.core.db import async_engine, init_models_for, make_engine, reinit_engine


def _ev(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_make_engine_and_init_models_for(tmp_path):
    """对临时 SQLite 建表返回表名列表。"""
    p = tmp_path / "t.db"
    eng = make_engine(f"sqlite+aiosqlite:///{p.as_posix()}")

    async def _run():
        tables = await init_models_for(eng)
        await eng.dispose()
        return tables
    tables = _ev(_run())
    assert len(tables) > 40 and "user" in tables and "document" in tables


def test_db_test_ok_and_bad_url():
    from app.api.v1.system_ops import DbUrlIn, db_test

    class U:
        tenant_id = 1
        id = 1

    # 合法 SQLite → ok
    r = _ev(db_test(DbUrlIn(database_url="sqlite+aiosqlite:///./data/_optest2.db"), user=U()))
    assert r["ok"] is True and r["kind"] == "sqlite"
    import os
    try:
        os.remove("./data/_optest2.db")
    except OSError:
        pass

    # 坏 URL（未装 asyncpg）→ 明确失败，不抛
    r2 = _ev(db_test(DbUrlIn(database_url="postgresql+asyncpg://bad:bad@127.0.0.1:59999/nope"), user=U()))
    assert r2["ok"] is False
    assert "asyncpg" in (r2.get("message") or "") or r2.get("driver_missing")


def test_install_driver_whitelist():
    """非白名单 target 被拒。"""
    from app.api.v1.system_ops import InstallDriverIn, db_install_driver
    from app.core.errors import ValidationError

    class U:
        tenant_id = 1
        id = 1

    try:
        _ev(db_install_driver(InstallDriverIn(target="evil-package"), user=U()))
        assert False, "非白名单应被拒"
    except ValidationError:
        pass


def test_db_init_endpoint(tmp_path):
    from app.api.v1.system_ops import DbUrlIn, db_init

    class U:
        tenant_id = 1
        id = 1

    p = tmp_path / "init.db"
    r = _ev(db_init(DbUrlIn(database_url=f"sqlite+aiosqlite:///{p.as_posix()}"), user=U()))
    assert r["ok"] is True and r["table_count"] > 40


def test_system_info_shape():
    from app.api.v1.system_ops import system_info

    class U:
        tenant_id = 1
        id = 1

    async def _run():
        from app.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await system_info(user=U(), db=db)
    info = _ev(_run())
    assert info["db_kind"] in ("sqlite", "postgres", "mysql")
    assert info["uptime_seconds"] >= 0
    assert "db_url_masked" in info and info["db_url_masked"].startswith("sqlite")


def test_pending_db_fallback(tmp_path, monkeypatch):
    """切库标记指向坏库 → 启动时自动回退到 previous，服务不锁死。"""
    import app.main as M
    import app.core.db as dbm

    orig = settings.database_url
    pending = DATA_DIR / "pending_db.txt"
    pending.write_text(json.dumps({
        "target_url": "postgresql+asyncpg://bad:bad@127.0.0.1:59999/nope",
        "previous_url": orig,
    }), encoding="utf-8")

    async def _run():
        await M._apply_pending_db()
        # 回退后 engine 应仍是原 SQLite 且可用
        from sqlalchemy import text
        async with dbm.async_engine.connect() as c:
            assert (await c.execute(text("SELECT 1"))).scalar() == 1
    try:
        _ev(_run())
        assert not pending.exists(), "pending 标记应被清理"
    finally:
        # 复原
        if pending.exists():
            pending.unlink()
        _ev(reinit_engine(orig))


def test_cleanup_removes_temp():
    from app.api.v1.system_ops import CleanupIn, system_cleanup

    class U:
        tenant_id = 1
        id = 1

    tmpf = DATA_DIR / "optmp_scratch.tmp"
    tmpf.write_bytes(b"x")

    async def _run():
        from app.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await system_cleanup(CleanupIn(scope="temp"), user=U(), db=db)
    r = _ev(_run())
    assert r["ok"] is True
    assert not tmpf.exists(), ".tmp 临时文件应被清理"


def test_cleanup_protects_active_db():
    """清理不得删除当前生效的数据库文件（防误删）。"""
    from app.api.v1.system_ops import CleanupIn, _sqlite_path, system_cleanup

    class U:
        tenant_id = 1
        id = 1

    cur = _sqlite_path(settings.database_url)
    assert cur is not None and cur.exists(), "测试库文件应存在"

    async def _run():
        from app.core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return await system_cleanup(CleanupIn(scope="all"), user=U(), db=db)
    _ev(_run())
    assert cur.exists(), "当前生效的数据库文件绝不能被清理删除"
