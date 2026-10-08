"""初始化种子数据：默认租户、管理员、默认 Provider 与模型配置。

用法：python scripts/seed.py
默认账号：admin / admin123
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bootstrap import seed_all


async def seed() -> None:
    await seed_all()
    print("种子数据完成。登录：admin / admin123")


if __name__ == "__main__":
    asyncio.run(seed())
