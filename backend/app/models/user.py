"""用户、用户组、角色、权限（预留完整 RBAC，本轮只用 user 与简化的 is_admin）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class User(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )

    department_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    avatar: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    # 本轮简化权限：租户内管理员；下轮由 user_role 取代
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # 用户类型：internal=公司内部用户 / external=外部客户（渠道自动建，不进内部列表）
    user_type: Mapped[str] = mapped_column(String(16), default="internal", index=True)
    # SSO 绑定（预留）
    sso_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sso_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settings: Mapped[str | None] = mapped_column(Text, nullable=True)
    # token 版本：改密码/停用/强制下线时 +1，使已签发的旧 token 立即失效（无需黑名单）
    token_version: Mapped[int] = mapped_column(default=0)
    # 注册审核：pending=待审核 / approved=已通过（默认，存量与管理员建号均为此）
    approval_status: Mapped[str] = mapped_column(String(16), default="approved")
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ===== 以下为下轮 RBAC 预留，本轮不写业务逻辑 =====


class UserGroup(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "user_group"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)


class UserGroupMember(Base, IdMixin):
    __tablename__ = "user_group_member"

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)


class Role(Base, IdMixin, TimestampMixin):
    __tablename__ = "role"

    tenant_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # null=系统内置
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), default="tenant")  # platform/tenant/department/kb
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)


class Permission(Base, IdMixin):
    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(32), default="")
    action: Mapped[str] = mapped_column(String(32), default="")


class RolePermission(Base, IdMixin):
    __tablename__ = "role_permission"

    role_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    permission_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)


class UserRole(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_role"

    tenant_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), default="tenant")
    scope_id: Mapped[int] = mapped_column(BigInteger, default=0)
    granted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
