"""租户与部门（组织树，预留完整树形结构）。"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class Tenant(Base, IdMixin, TimestampMixin):
    __tablename__ = "tenant"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    plan: Mapped[str] = mapped_column(String(32), default="default")
    settings: Mapped[str | None] = mapped_column(Text, nullable=True)  # 预留 JSON


class Department(Base, IdMixin, TimestampMixin, TenantMixin):
    """部门树：邻接表 + path（点分隔）+ depth，为下轮部门级授权预留。"""

    __tablename__ = "department"

    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str] = mapped_column(String(512), default="", index=True)  # 如 "1.3.7."
    depth: Mapped[int] = mapped_column(Integer, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
