"""RBAC 相关 DTO：角色、权限、用户、部门、用户组。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---- 角色 ----
class RoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    scope: str = "tenant"  # platform/tenant/department/kb
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    scope: str
    is_system: bool
    description: str | None = None

    model_config = {"from_attributes": True}


class RolePermissionsIn(BaseModel):
    permission_ids: list[int]


class PermissionOut(BaseModel):
    id: int
    code: str
    name: str
    resource: str
    action: str

    model_config = {"from_attributes": True}


# ---- 用户 ----
class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    email: str | None = None
    department_id: int | None = None
    is_admin: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    department_id: int | None = None
    status: str | None = None


class UserListItem(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None = None
    status: str
    is_admin: bool
    department_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserRoleGrant(BaseModel):
    role_id: int
    scope_type: str = "tenant"  # platform/tenant/department/kb
    scope_id: int = 0
    expires_at: datetime | None = None


class UserRoleOut(BaseModel):
    id: int
    user_id: int
    role_id: int
    role_code: str | None = None
    role_name: str | None = None
    scope_type: str
    scope_id: int
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


# ---- 部门 ----
class DeptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    code: str | None = None
    sort: int = 0


class DeptUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    sort: int | None = None
    parent_id: int | None = None  # 传值即移动


class DeptOut(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    code: str | None = None
    path: str
    depth: int
    sort: int

    model_config = {"from_attributes": True}


class DeptTreeNode(DeptOut):
    children: list["DeptTreeNode"] = []


# ---- 用户组 ----
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = None


class GroupOut(BaseModel):
    id: int
    name: str
    description: str | None = None

    model_config = {"from_attributes": True}


class GroupMembersIn(BaseModel):
    user_ids: list[int]
