"""pytest 配置：使用独立测试库，避免污染开发数据。

必须在导入任何 app 模块前设置环境变量（settings 与 db engine 在导入时初始化）。
"""
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 独立测试库
_TEST_DB = BACKEND_DIR / "data" / "test_rag.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}"
os.environ["EMBEDDING_DIM"] = "64"
os.environ["TASK_BACKEND"] = "memory"


@pytest.fixture(scope="session")
def event_loop():
    """兼容旧式 fixture 写法：提供 session 级事件循环。"""
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
