"""鉴权相关 DTO。"""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


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
