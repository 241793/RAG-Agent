"""数据库：async engine / session / Base，以及跨库向量类型 VectorType。

VectorType 设计：
- PostgreSQL: 使用原生 vector(n) 列（需 pgvector 扩展）
- SQLite / MySQL: 以 float32 二进制 BLOB 存储，检索在应用层用 numpy 计算
这样同一套 ORM 模型可在三种库间迁移，向量检索后端通过 settings 切换。
"""
from __future__ import annotations

import struct
from typing import Any

from sqlalchemy import Float, LargeBinary, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


class VectorType(TypeDecorator):
    """跨数据库向量列。

    读取时统一返回 list[float]；写入接受 list[float]。
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, dim: int | None = None, *args: Any, **kwargs: Any) -> None:
        self.dim = dim or settings.embedding_dim
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and settings.resolved_vector_backend == "pgvector":
            try:
                from pgvector.sqlalchemy import Vector  # type: ignore

                return dialect.type_descriptor(Vector(self.dim))
            except ImportError:
                pass
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql" and settings.resolved_vector_backend == "pgvector":
            return value  # pgvector 自行处理
        # 其余库：float32 紧凑二进制
        return struct.pack(f"<{len(value)}f", *value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql" and settings.resolved_vector_backend == "pgvector":
            return list(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            b = bytes(value)
            n = len(b) // 4
            return list(struct.unpack(f"<{n}f", b))
        return value


# ---- engine / session ----
_engine_kwargs: dict[str, Any] = {"echo": False, "future": True}
if settings.is_sqlite:
    # timeout: 遇到锁时等待（秒），而非立即失败；SQLite 单写者，需容忍短暂争锁
    _engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
else:
    _engine_kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)

async_engine = create_async_engine(settings.database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(async_engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    """SQLite 开启 WAL，降低读写锁冲突。"""
    if settings.is_sqlite:
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()


async def get_db() -> AsyncSession:
    """FastAPI 依赖：每请求一个 session。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """开发用：直接建表 + 补列（生产用 alembic）。"""
    # 确保所有模型被导入注册
    import app.models  # noqa: F401

    async with async_engine.begin() as conn:
        if settings.is_postgres:
            from sqlalchemy import text

            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # create_all 不会给已存在的表加列：检测缺失列并 ALTER TABLE 补上
        await conn.run_sync(_sync_missing_columns)


def _sync_missing_columns(sync_conn) -> None:
    """对比 ORM 定义与现有表结构，补齐缺失列（仅 SQLite/简单场景）。"""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in cols:
                continue
            # 生成 ALTER TABLE ADD COLUMN（类型用 SQLite 兼容写法）
            coltype = col.type.compile(dialect=sync_conn.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
            try:
                sync_conn.execute(text(ddl))
            except Exception:  # noqa: BLE001
                pass  # 已有列 / 不支持的类型，忽略
