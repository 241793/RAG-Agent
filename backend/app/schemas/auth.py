"""鉴权相关 DTO。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # 限制长度，防超长输入 DoS / 撞哈希
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=256)  # 申请理由（供管理员审核参考）


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


class RoleBrief(BaseModel):
    id: int
    code: str
    name: str


class UserOut(BaseModel):
    id: int
    tenant_id: int
    username: str
    display_name: str
    email: str | None = None
    avatar: str | None = None
    is_admin: bool = False
    department_id: int | None = None
    department_name: str | None = None
    roles: list[RoleBrief] = []
    permissions: list[str] = []

    model_config = {"from_attributes": True}
