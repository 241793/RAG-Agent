"""权限过滤唯一入口（企业越权防护核心）。

设计要点：
- 所有授权对象（人/部门/角色/组/公开）压到同一整数空间（principal 编码），
  使权限判定可纯计算、可直接参与 SQL 过滤。
- 所有检索 SQL 的权限 WHERE 片段必须由本模块 build_permission_filter() 生成，
  禁止在检索代码里散落权限条件（越权最高危点）。
- 本轮：仅用到 USER 与 PUBLIC；部门/角色/组编码先落地，下轮直接扩展。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# principal 编码基数
PUBLIC = 0
USER_BASE = 1_000_000_000_000
DEPT_BASE = 2_000_000_000_000
ROLE_BASE = 3_000_000_000_000
GROUP_BASE = 4_000_000_000_000


def user_principal(user_id: int) -> int:
    return USER_BASE + user_id


def dept_principal(dept_id: int) -> int:
    return DEPT_BASE + dept_id


def role_principal(role_id: int) -> int:
    return ROLE_BASE + role_id


def group_principal(group_id: int) -> int:
    return GROUP_BASE + group_id


@dataclass
class PrincipalSet:
    """某次请求的主体集合（查询期解析，可缓存）。"""

    user_id: int
    tenant_id: int
    is_admin: bool = False
    is_external: bool = False  # 外部客户（渠道用户）：不得读 internal 内部库
    dept_ids: list[int] = field(default_factory=list)
    role_ids: list[int] = field(default_factory=list)
    group_ids: list[int] = field(default_factory=list)

    @property
    def principals(self) -> list[int]:
        """展开为 principal 整数集合（含 PUBLIC）。"""
        ps = [PUBLIC, user_principal(self.user_id)]
        ps += [dept_principal(d) for d in self.dept_ids]
        ps += [role_principal(r) for r in self.role_ids]
        ps += [group_principal(g) for g in self.group_ids]
        return ps


@dataclass
class PermissionFilter:
    """权限过滤片段：租户 + KB 白名单 + 文档级 ACL 主体集合。"""

    tenant_id: int
    accessible_kb_ids: list[int]
    principals: list[int] = field(default_factory=list)
    # 管理员或为空表示不受 KB 白名单限制（仍需租户隔离）
    bypass_kb: bool = False
    # API Key 等场景的强制 KB 限制（与 accessible_kb_ids 取交集）
    force_kb_ids: list[int] | None = None


def build_doc_acl_clause(principals: list[int], dialect: str, col: str = "chunk") -> str:
    """生成文档级 ACL 过滤 SQL 片段（可直接嵌入 WHERE）。

    语义（与 NumpyStore 的 Python 版 _chunk_visible_py 完全一致）：
        vis_scope IN (0,1)  OR  (vis_scope=2 AND acl_allow 命中 且 acl_deny 未命中)

    principals 为整数（含 PUBLIC=0），内联无注入风险。
    col 为表别名/前缀（默认 "chunk"）。
    """
    ints = ",".join(str(int(p)) for p in principals) or "0"
    scope_col = f"{col}.vis_scope" if col else "vis_scope"
    allow_col = f"{col}.acl_allow" if col else "acl_allow"
    deny_col = f"{col}.acl_deny" if col else "acl_deny"

    if dialect == "postgresql":
        arr = "{" + ",".join(str(int(p)) for p in principals) + "}"
        return (
            f"({scope_col} IN (0,1) OR ({scope_col} = 2 "
            f"AND ({allow_col}::jsonb ?| ARRAY['{arr}']::text[]) "
            f"AND NOT (COALESCE({deny_col}, '[]')::jsonb ?| ARRAY['{arr}']::text[])))"
        )
    if dialect == "mysql":
        arr = "[" + ",".join(str(int(p)) for p in principals) + "]"
        return (
            f"({scope_col} IN (0,1) OR ({scope_col} = 2 "
            f"AND JSON_OVERLAPS(COALESCE({allow_col}, JSON_ARRAY()), CAST('{arr}' AS JSON)) "
            f"AND NOT JSON_OVERLAPS(COALESCE({deny_col}, JSON_ARRAY()), CAST('{arr}' AS JSON))))"
        )
    # sqlite（JSON1）
    return (
        f"({scope_col} IN (0,1) OR ({scope_col} = 2 "
        f"AND EXISTS (SELECT 1 FROM json_each(COALESCE({allow_col}, '[]')) ja WHERE CAST(ja.value AS INTEGER) IN ({ints})) "
        f"AND NOT EXISTS (SELECT 1 FROM json_each(COALESCE({deny_col}, '[]')) jd WHERE CAST(jd.value AS INTEGER) IN ({ints}))))"
    )


def chunk_visible_py(principals: set[int], vis_scope: int, allow, deny) -> bool:
    """Python 版可见性判定（NumpyStore 纵深防御，与 build_doc_acl_clause 同语义）。"""
    if vis_scope in (0, 1):
        return True
    if vis_scope != 2:
        return False
    if not (set(allow or []) & principals):
        return False
    return not (set(deny or []) & principals)


def build_kb_visibility_clause(principals: list[int]) -> tuple[str, list]:
    """生成 kb_member 查询的可见性判定（供 accessible_kb_ids 使用）。

    返回 (SQL 片段, 参数)。公开 KB 用 principal_id=0 表达。
    """
    placeholders = ",".join("?" * len(principals))
    sql = f"(principal_id = 0 OR principal_id IN ({placeholders}))"
    return sql, list(principals)


def build_permission_filter(
    principal_set: PrincipalSet,
    accessible_kb_ids: list[int],
    force_kb_ids: list[int] | None = None,
) -> PermissionFilter:
    """构建权限过滤对象。accessible_kb_ids 由上层查库得出并传入。

    force_kb_ids：API Key 场景的强制 KB 限制，与可访问集合取交集。
    """
    if force_kb_ids is not None:
        allowed = set(force_kb_ids)
        accessible_kb_ids = [k for k in accessible_kb_ids if k in allowed]
        bypass = False  # 强制限制时不允许绕过
    else:
        bypass = principal_set.is_admin
    return PermissionFilter(
        tenant_id=principal_set.tenant_id,
        accessible_kb_ids=accessible_kb_ids,
        principals=principal_set.principals,
        bypass_kb=bypass,
        force_kb_ids=force_kb_ids,
    )


def filter_accessible_kbs(principal_set: PrincipalSet, kb_rows: list[dict]) -> list[int]:
    """应用层过滤：给定 KB 列表（含 visibility 与 member principal 列表），
    返回该主体可访问的 kb_id 列表。

    kb_row 形如：{"kb_id":1, "visibility":"internal", "principals":[0, 1e12..]}
    visibility 三值语义：
    - public : 本租户全员可见
    - internal: 本租户登录用户可见（无需是成员）
    - private: 仅 owner 与显式成员（principal 命中）可见
    管理员不受限（由上层 bypass，这里对 admin 直接放行全部）。
    """
    if principal_set.is_admin:
        return [row["kb_id"] for row in kb_rows]
    pset = set(principal_set.principals)
    out: list[int] = []
    for row in kb_rows:
        vis = row.get("visibility")
        if vis == "public":
            out.append(row["kb_id"])
            continue
        if vis == "internal" and not principal_set.is_external:
            # internal = 本租户内部用户可见；外部客户（渠道）不得命中
            out.append(row["kb_id"])
            continue
        # private，或外部主体遇 internal：需显式成员 principal 命中
        members = set(row.get("principals") or [])
        if members & pset:
            out.append(row["kb_id"])
    return out
