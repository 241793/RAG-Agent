"""SSO 配置模型：每个身份源一行。"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TenantMixin, TimestampMixin


class SsoConfig(Base, IdMixin, TimestampMixin, TenantMixin):
    __tablename__ = "sso_config"

    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # oidc/wecom/dingtalk/feishu
    name: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    client_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # OIDC / 通用
    authorize_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    userinfo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scopes: Mapped[str] = mapped_column(String(256), default="openid profile email")
    # 企业微信/钉钉/飞书额外参数
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corp_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    redirect_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 属性映射：{"username": "...", "email": "...", "display_name": "...", "dept_code": "...", "groups": "..."}
    attribute_map: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    default_role_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    auto_create_user: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_dept: Mapped[bool] = mapped_column(Boolean, default=False)
