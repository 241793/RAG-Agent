"""系统设置覆盖项：管理员在 Web 上修改的配置，存库、启动时叠加到 Settings。

与 .env 的关系：.env 提供默认值；本表的行在启动时覆盖到 settings 单例（热生效），
少数启动期读取的项（端口/日志/DB URL 等）需重启进程后才真正生效。
"""
from __future__ import annotations

from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class SystemSetting(Base, IdMixin, TimestampMixin):
    __tablename__ = "system_setting"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
