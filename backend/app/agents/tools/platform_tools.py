"""平台运营类 AI 工具：用量查询、组织查询、审计查询 + 写操作（HITL）。

被 admin_tools.ADMIN_TOOLS 收集，供问答页/智能体按权限调用。
"""
from __future__ import annotations

from sqlalchemy import select

from app.agents.tools.base import ToolContext, ToolResult, WriteToolMixin

_WriteToolMixin = WriteToolMixin


# ==================== 用量 / 组织 / 审计 查询（read）====================
class QueryUsageTool:
    name = "query_usage"
    description = "查询平台 token 用量与调用统计（今日/近N天，可按模型）。用户问“今天消耗多少 token/用量统计”时使用。"
    required_permission = "model:read"
    kind = "read"
    parameters = {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "统计最近多少天，默认 1（=今天）", "default": 1},
            "by_model": {"type": "boolean", "description": "是否按模型分组", "default": False},
        },
    }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func

        from app.models import UsageLog

        days = max(1, min(int(args.get("days") or 1), 90))
        since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
        row = (await ctx.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0),
                func.coalesce(func.sum(UsageLog.total_tokens), 0),
                func.coalesce(func.sum(UsageLog.cached_tokens), 0),
            ).where(UsageLog.tenant_id == ctx.tenant_id, UsageLog.created_at >= since_ms)
        )).one()
        calls, pt, ct, tt, cached = (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), int(row[3] or 0), int(row[4] or 0))
        lines = [
            f"统计范围：最近 {days} 天",
            f"调用次数：{calls}",
            f"输入 token：{pt}",
            f"输出 token：{ct}",
            f"总 token：{tt}",
            f"命中缓存 token：{cached}",
        ]
        if args.get("by_model"):
            mr = (await ctx.db.execute(
                select(UsageLog.model, func.sum(UsageLog.total_tokens))
                .where(UsageLog.tenant_id == ctx.tenant_id, UsageLog.created_at >= since_ms)
                .group_by(UsageLog.model)
            )).all()
            if mr:
                lines.append("按模型：")
                lines += [f"  {m or '未知'}：{int(t or 0)} tokens" for m, t in mr]
        return ToolResult(content="\n".join(lines), data={"total_tokens": tt, "calls": calls, "days": days})


class ListUsersTool:
    name = "list_users"
    description = "列出本租户用户（含 id/用户名/显示名/是否管理员）。"
    required_permission = "user:read"
    kind = "read"
    parameters = {"type": "object", "properties": {
        "search": {"type": "string", "description": "可选，按用户名模糊筛选"},
    }}

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import User

        q = select(User).where(User.tenant_id == ctx.tenant_id)
        s = str(args.get("search") or "").strip()
        if s:
            q = q.where(User.username.like(f"%{s}%"))
        rows = (await ctx.db.execute(q.limit(200))).scalars().all()
        if not rows:
            return ToolResult(content="（暂无用户）", data={"count": 0})
        lines = [f"[{u.id}] {u.username}（{u.display_name or '-'}）{'管理员' if u.is_admin else ''}" for u in rows]
        return ToolResult(content="\n".join(lines), data={"count": len(rows)})


class ListRolesTool:
    name = "list_roles"
    description = "列出角色（含内置与自定义）。"
    required_permission = "role:read"
    kind = "read"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Role

        rows = (await ctx.db.execute(select(Role).limit(200))).scalars().all()
        lines = [f"[{r.id}] {r.name}（{r.code}）scope={r.scope}" for r in rows]
        return ToolResult(content="\n".join(lines) or "（暂无角色）", data={"count": len(rows)})


class ListDeptsTool:
    name = "list_depts"
    description = "列出部门。"
    required_permission = "dept:read"
    kind = "read"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Department

        rows = (await ctx.db.execute(
            select(Department).where(Department.tenant_id == ctx.tenant_id).limit(300)
        )).scalars().all()
        lines = [f"[{d.id}] {d.name}（父={d.parent_id or '根'}）" for d in rows]
        return ToolResult(content="\n".join(lines) or "（暂无部门）", data={"count": len(rows)})


class ListScheduledTool:
    name = "list_scheduled_tasks"
    description = "列出定时任务（含 id/名称/启用状态/类型）。"
    required_permission = "schedule:read"
    kind = "read"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ScheduledTask

        rows = (await ctx.db.execute(
            select(ScheduledTask).where(ScheduledTask.tenant_id == ctx.tenant_id).limit(100)
        )).scalars().all()
        lines = [f"[{t.id}] {t.name} | 启用={t.enabled} | 类型={t.target_type}" for t in rows]
        return ToolResult(content="\n".join(lines) or "（暂无定时任务）", data={"count": len(rows)})


class ListTaskRunsTool:
    name = "list_task_runs"
    description = ("查看某个定时任务的执行历史（状态/耗时/结果/错误）。"
                   "当用户问「某个定时任务跑成功了吗」「最近执行结果」时使用。")
    required_permission = "schedule:read"
    kind = "read"
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "定时任务 id（先用 list_scheduled_tasks 查）"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["task_id"],
    }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ScheduledTask, ScheduledTaskRun

        tid = int(args.get("task_id") or 0)
        t = await ctx.db.get(ScheduledTask, tid)
        if not t or t.tenant_id != ctx.tenant_id:
            return ToolResult(content="定时任务不存在", is_error=True)
        limit = max(1, min(int(args.get("limit") or 10), 50))
        rows = (
            await ctx.db.execute(
                select(ScheduledTaskRun)
                .where(ScheduledTaskRun.task_id == tid)
                .order_by(ScheduledTaskRun.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        if not rows:
            return ToolResult(content=f"任务「{t.name}」暂无执行记录")
        lines = [f"任务「{t.name}」最近 {len(rows)} 次执行："]
        for r in rows:
            import time as _t

            when = _t.strftime("%Y-%m-%d %H:%M", _t.localtime((r.started_at or 0) / 1000)) if r.started_at else "-"
            dur = f"{r.duration_ms / 1000:.1f}s" if r.duration_ms else "-"
            detail = (r.error or r.output or "")[:200]
            lines.append(f"- [{when}] {r.status} 耗时{dur}（第{r.attempt}次）{detail}")
        return ToolResult(content="\n".join(lines), data={"count": len(rows)})


class QueryAuditTool:
    name = "query_audit_logs"
    description = "查询审计日志（最近记录，可按动作前缀筛选）。"
    required_permission = "audit:read"
    kind = "read"
    parameters = {
        "type": "object", "properties": {
            "action": {"type": "string", "description": "按动作前缀筛选，如 user / doc / kb"},
            "limit": {"type": "integer", "default": 20},
        },
    }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import AuditLog

        q = select(AuditLog).where(AuditLog.tenant_id == ctx.tenant_id)
        a = str(args.get("action") or "").strip()
        if a:
            q = q.where(AuditLog.action.like(f"{a}%"))
        lim = max(1, min(int(args.get("limit") or 20), 100))
        rows = (await ctx.db.execute(q.order_by(AuditLog.id.desc()).limit(lim))).scalars().all()
        lines = [f"[{r.action}] {r.resource_type or ''}#{r.resource_id or ''} {r.result}" for r in rows]
        return ToolResult(content="\n".join(lines) or "（暂无审计记录）", data={"count": len(rows)})


class ListChannelsTool:
    name = "list_channels"
    description = "列出外部渠道（QQ/微信/企业微信/飞书及其状态）。"
    required_permission = "channel:read"
    kind = "read"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Channel

        rows = (await ctx.db.execute(
            select(Channel).where(Channel.tenant_id == ctx.tenant_id, Channel.status == "active").limit(50)
        )).scalars().all()
        lines = [f"[{c.id}] {c.kind} {c.name} | 启用={c.enabled} | 连接={c.connected}" for c in rows]
        return ToolResult(content="\n".join(lines) or "（暂无外部渠道）", data={"count": len(rows)})


class ListModelsTool:
    name = "list_models"
    description = "列出已配置的模型（对话/向量/重排）。"
    required_permission = "model:read"
    kind = "read"
    parameters = {"type": "object", "properties": {}}

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ModelConfig

        rows = (await ctx.db.execute(
            select(ModelConfig).where(
                (ModelConfig.tenant_id == ctx.tenant_id) | (ModelConfig.tenant_id.is_(None))
            ).limit(100)
        )).scalars().all()
        lines = [f"[{m.id}] {m.purpose} {m.display_name or m.model_name}" for m in rows]
        return ToolResult(content="\n".join(lines) or "（暂无模型配置）", data={"count": len(rows)})


# ==================== 写操作（HITL）====================
class UpdateKbTool(_WriteToolMixin):
    name = "update_kb"
    description = "修改知识库的名称/描述/可见性。写操作，需确认后生效。"
    required_permission = "kb:update"
    parameters = {
        "type": "object", "properties": {
            "kb_id": {"type": "integer"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "visibility": {"type": "string", "enum": ["public", "internal", "private"]},
        }, "required": ["kb_id"],
    }

    def summarize(self, args: dict) -> str:
        return f"修改知识库 #{args.get('kb_id')}：" + "、".join(f"{k}={v}" for k, v in args.items() if k != "kb_id")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import KnowledgeBase

        kb = await ctx.db.get(KnowledgeBase, int(args.get("kb_id") or 0))
        if not kb or kb.tenant_id != ctx.tenant_id:
            return ToolResult(content="知识库不存在", is_error=True)
        for f in ("name", "description", "visibility"):
            if args.get(f) is not None:
                setattr(kb, f, args[f])
        await ctx.db.flush()
        return ToolResult(content=f"已更新知识库 #{kb.id}")


class DeleteDocumentTool(_WriteToolMixin):
    name = "delete_document"
    description = "删除某文档。危险写操作，需确认后生效。"
    required_permission = "doc:delete"
    parameters = {"type": "object", "properties": {"doc_id": {"type": "integer"}}, "required": ["doc_id"]}

    def summarize(self, args: dict) -> str:
        return f"删除文档 #{args.get('doc_id')}（不可恢复）"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from sqlalchemy import delete as _del

        from app.models import Chunk, Document

        doc = await ctx.db.get(Document, int(args.get("doc_id") or 0))
        if not doc or doc.tenant_id != ctx.tenant_id:
            return ToolResult(content="文档不存在", is_error=True)
        await ctx.db.execute(_del(Chunk).where(Chunk.doc_id == doc.id))
        await ctx.db.delete(doc)
        await ctx.db.flush()
        return ToolResult(content=f"已删除文档 #{doc.id}")


class CreateFolderTool(_WriteToolMixin):
    name = "create_folder"
    description = "在知识库内创建文件夹。写操作，需确认后生效。"
    required_permission = "doc:update"
    parameters = {
        "type": "object", "properties": {
            "kb_id": {"type": "integer"},
            "name": {"type": "string"},
        }, "required": ["kb_id", "name"],
    }

    def summarize(self, args: dict) -> str:
        return f"在知识库 #{args.get('kb_id')} 创建文件夹「{args.get('name')}」"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import DocumentFolder

        f = DocumentFolder(tenant_id=ctx.tenant_id, kb_id=int(args.get("kb_id") or 0),
                           name=str(args.get("name") or "新建文件夹"))
        ctx.db.add(f)
        await ctx.db.flush()
        return ToolResult(content=f"已创建文件夹 #{f.id}")


class ToggleScheduledTool(_WriteToolMixin):
    name = "toggle_scheduled_task"
    description = "启用/停用定时任务。写操作，需确认后生效。"
    required_permission = "schedule:manage"
    parameters = {
        "type": "object", "properties": {
            "task_id": {"type": "integer"},
            "enabled": {"type": "boolean"},
        }, "required": ["task_id", "enabled"],
    }

    def summarize(self, args: dict) -> str:
        return f"{'启用' if args.get('enabled') else '停用'}定时任务 #{args.get('task_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ScheduledTask

        t = await ctx.db.get(ScheduledTask, int(args.get("task_id") or 0))
        if not t or t.tenant_id != ctx.tenant_id:
            return ToolResult(content="定时任务不存在", is_error=True)
        t.enabled = bool(args.get("enabled"))
        await ctx.db.flush()
        return ToolResult(content=f"已{'启用' if t.enabled else '停用'}任务 #{t.id}")


class AddKbMemberTool(_WriteToolMixin):
    name = "add_kb_member"
    description = "给知识库添加成员（按用户 id）。写操作，需确认后生效。"
    required_permission = "kb:member_manage"
    parameters = {
        "type": "object", "properties": {
            "kb_id": {"type": "integer"},
            "user_id": {"type": "integer", "description": "user 类型时填用户 id"},
            "principal_type": {"type": "string", "enum": ["user", "department", "role", "group"], "default": "user"},
            "principal_id": {"type": "integer", "description": "非 user 类型时填对应实体 id（部门/角色/用户组）"},
            "perm_level": {"type": "string", "enum": ["viewer", "editor", "manager"], "default": "viewer"},
        }, "required": ["kb_id"],
    }

    def summarize(self, args: dict) -> str:
        pt = args.get("principal_type") or "user"
        ref = args.get("principal_id") if pt != "user" else args.get("user_id")
        return f"给知识库 #{args.get('kb_id')} 添加 {pt}#{ref}（{args.get('perm_level', 'viewer')}）"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import KBMember, KnowledgeBase
        from app.services import permission as P

        kb = await ctx.db.get(KnowledgeBase, int(args.get("kb_id") or 0))
        if not kb or kb.tenant_id != ctx.tenant_id:
            return ToolResult(content="知识库不存在", is_error=True)
        ptype = args.get("principal_type") or "user"
        mapping = {"user": P.user_principal, "department": P.dept_principal,
                   "role": P.role_principal, "group": P.group_principal}
        if ptype not in mapping:
            return ToolResult(content="principal_type 必须为 user/department/role/group", is_error=True)
        ref = args.get("user_id") if ptype == "user" else args.get("principal_id")
        if ref is None:
            return ToolResult(content="缺少授权对象 id", is_error=True)
        pid = mapping[ptype](int(ref))
        exist = (await ctx.db.execute(
            select(KBMember).where(KBMember.kb_id == kb.id, KBMember.principal_id == pid)
        )).scalar_one_or_none()
        lvl = str(args.get("perm_level") or "viewer")
        if exist:
            exist.perm_level = lvl
        else:
            ctx.db.add(KBMember(tenant_id=ctx.tenant_id, kb_id=kb.id, principal_id=pid,
                                perm_level=lvl, granted_by=ctx.user_id))
        await ctx.db.flush()
        return ToolResult(content=f"已添加 {ptype} 到知识库 #{kb.id}")


PLATFORM_TOOLS = [
    QueryUsageTool(), ListUsersTool(), ListRolesTool(), ListDeptsTool(),
    ListScheduledTool(), QueryAuditTool(), ListChannelsTool(), ListModelsTool(),
    ListTaskRunsTool(),
    UpdateKbTool(), DeleteDocumentTool(), CreateFolderTool(),
    ToggleScheduledTool(), AddKbMemberTool(),
]
