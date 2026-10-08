"""审计日志模型。

记录关键写操作（登录、授权变更、增删改等），供合规追溯。
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import BigIntPK


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")  # user/apikey/system
    actor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)  # e.g. user.login
    resource_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="success")  # success/failure
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0, index=True)  # 毫秒时间戳
