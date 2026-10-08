"""管理员 AI 操作工具（全量）：定时任务全生命周期、RBAC、KB、智能体、API Key、
文档批量/ACL、渠道、工作流、模型配置。

全部进 admin_tools.ADMIN_TOOLS，按 required_permission 权限过滤；write 走 HITL。
"""
from __future__ import annotations

from sqlalchemy import delete as _delete
from sqlalchemy import select

from app.agents.tools.base import ToolContext, ToolResult, WriteToolMixin


# ==================== 定时任务全生命周期 ====================
class CreateScheduledTaskTool(WriteToolMixin):
    name = "create_scheduled_task"
    description = ("创建定时任务。支持 cron(周期)、interval(每N秒)、once(一次)。"
                   "「X 分钟后提醒」用 delay_seconds=X（自动转一次性）。"
                   "target_type=prompt 时用 prompt；=workflow 时用 inputs。"
                   "notify_on 控制通知时机：always/success/fail/never（默认 fail=仅失败通知）。"
                   "执行结果只留在定时任务页的执行记录，不占用问答会话。")
    required_permission = "schedule:manage"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "任务名"},
            "agent_id": {"type": "integer", "description": "归属智能体 id（先用 list_agents 查）"},
            "target_type": {"type": "string", "enum": ["prompt", "workflow"], "default": "prompt"},
            "prompt": {"type": "string", "description": "prompt 目标：要执行的提示词"},
            "inputs": {"type": "object", "description": "workflow 目标：输入参数"},
            "schedule_kind": {"type": "string", "enum": ["cron", "interval", "once"], "default": "cron"},
            "cron_expr": {"type": "string", "description": "cron 表达式，如 0 9 * * *"},
            "interval_seconds": {"type": "integer", "description": "每 N 秒（≥60）"},
            "delay_seconds": {"type": "integer", "description": "X 秒后执行一次（便捷，自动转 once）"},
            "run_at": {"type": "integer", "description": "once 的绝对时间戳(ms)"},
            "trigger_kind": {"type": "string", "enum": ["schedule", "event"], "default": "schedule",
                             "description": "schedule=按时间；event=按事件触发"},
            "event_name": {"type": "string",
                           "description": "event 触发时的事件名：document.ready / document.failed / workflow.completed / workflow.failed"},
            "notify_on": {"type": "string", "enum": ["always", "success", "fail", "never"],
                          "description": "通知时机（默认 fail）"},
            "enabled": {"type": "boolean", "default": True},
        },
        "required": ["name", "agent_id"],
    }

    def summarize(self, args: dict) -> str:
        parts = [f"创建定时任务「{args.get('name')}」"]
        if args.get("delay_seconds"):
            parts.append(f"{args['delay_seconds']} 秒后执行一次")
        elif args.get("schedule_kind") == "interval":
            parts.append(f"每 {args.get('interval_seconds')} 秒")
        elif args.get("schedule_kind") == "once":
            parts.append("执行一次")
        else:
            parts.append(f"按 cron「{args.get('cron_expr')}」")
        return "，".join(parts)

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.services.schedule_service import create_task

        t = await create_task(ctx.db, tenant_id=ctx.tenant_id, owner_id=ctx.user_id, data=args)
        return ToolResult(content=f"已创建定时任务 #{t.id}「{t.name}」", data={"id": t.id})


class UpdateScheduledTaskTool(WriteToolMixin):
    name = "update_scheduled_task"
    description = "修改定时任务（名称/提示词/调度等）。"
    required_permission = "schedule:manage"
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "integer"}, "name": {"type": "string"},
                       "prompt": {"type": "string"}, "schedule_kind": {"type": "string"},
                       "cron_expr": {"type": "string"}, "interval_seconds": {"type": "integer"},
                       "delay_seconds": {"type": "integer"}, "enabled": {"type": "boolean"},
                       "agent_id": {"type": "integer"}},
        "required": ["task_id"],
    }

    def summarize(self, args: dict) -> str:
        return f"修改定时任务 #{args.get('task_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ScheduledTask
        from app.services.schedule_service import update_task

        t = await ctx.db.get(ScheduledTask, int(args.get("task_id") or 0))
        if not t or t.tenant_id != ctx.tenant_id:
            return ToolResult(content="定时任务不存在", is_error=True)
        data = {k: v for k, v in args.items() if k != "task_id"}
        # update_task 需要完整调度字段，缺的用现值兜底
        merged = {
            "name": data.get("name", t.name), "agent_id": data.get("agent_id", t.agent_id),
            "target_type": t.target_type, "prompt": data.get("prompt", t.prompt),
            "inputs": t.inputs, "schedule_kind": data.get("schedule_kind", t.schedule_kind),
            "cron_expr": data.get("cron_expr", t.cron_expr),
            "interval_seconds": data.get("interval_seconds", t.interval_seconds),
            "run_at": t.run_at, "delay_seconds": data.get("delay_seconds"),
            "trigger_kind": t.trigger_kind, "event_name": t.event_name,
            "max_retries": t.max_retries, "retry_interval_seconds": t.retry_interval_seconds,
            "timeout_seconds": t.timeout_seconds, "enabled": data.get("enabled", t.enabled),
        }
        await update_task(ctx.db, t, merged)
        return ToolResult(content=f"已更新定时任务 #{t.id}")


class DeleteScheduledTaskTool(WriteToolMixin):
    name = "delete_scheduled_task"
    description = "删除定时任务。"
    required_permission = "schedule:manage"
    dangerous = True
    parameters = {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}

    def summarize(self, args: dict) -> str:
        return f"删除定时任务 #{args.get('task_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ScheduledTask, ScheduledTaskRun

        t = await ctx.db.get(ScheduledTask, int(args.get("task_id") or 0))
        if not t or t.tenant_id != ctx.tenant_id:
            return ToolResult(content="定时任务不存在", is_error=True)
        await ctx.db.execute(_delete(ScheduledTaskRun).where(ScheduledTaskRun.task_id == t.id))
        await ctx.db.delete(t)
        await ctx.db.flush()
        return ToolResult(content=f"已删除定时任务 #{t.id}")


class RunScheduledTaskNowTool(WriteToolMixin):
    name = "run_scheduled_task_now"
    description = "立即运行一个定时任务（手动触发一次）。"
    required_permission = "schedule:manage"
    parameters = {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}

    def summarize(self, args: dict) -> str:
        return f"立即运行定时任务 #{args.get('task_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        import asyncio

        from app.models import ScheduledTask
        from app.tasks.scheduler_tasks import execute_task

        t = await ctx.db.get(ScheduledTask, int(args.get("task_id") or 0))
        if not t or t.tenant_id != ctx.tenant_id:
            return ToolResult(content="定时任务不存在", is_error=True)
        asyncio.create_task(execute_task(t.id, manual=True))
        return ToolResult(content=f"已触发运行任务 #{t.id}")


# ==================== RBAC 写操作 ====================
class CreateUserTool(WriteToolMixin):
    name = "create_user"
    description = "创建用户（username/password/display_name/email/department_id/is_admin）。"
    required_permission = "user:manage"
    parameters = {
        "type": "object",
        "properties": {
            "username": {"type": "string"}, "password": {"type": "string"},
            "display_name": {"type": "string"}, "email": {"type": "string"},
            "department_id": {"type": "integer"}, "is_admin": {"type": "boolean", "default": False},
        }, "required": ["username", "password"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建用户「{args.get('username')}」" + ("（管理员）" if args.get("is_admin") else "")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.core.security import hash_password
        from app.models import User

        uname = str(args.get("username") or "").strip()
        if not uname:
            return ToolResult(content="用户名不能为空", is_error=True)
        exist = (await ctx.db.execute(
            select(User).where(User.tenant_id == ctx.tenant_id, User.username == uname)
        )).scalar_one_or_none()
        if exist:
            return ToolResult(content=f"用户 {uname} 已存在", is_error=True)
        u = User(tenant_id=ctx.tenant_id, username=uname,
                 password_hash=hash_password(str(args.get("password") or "")),
                 display_name=str(args.get("display_name") or uname),
                 email=args.get("email"), department_id=args.get("department_id"),
                 is_admin=bool(args.get("is_admin")))
        ctx.db.add(u)
        await ctx.db.flush()
        return ToolResult(content=f"已创建用户 #{u.id}「{uname}」", data={"id": u.id})


class UpdateUserTool(WriteToolMixin):
    name = "update_user"
    description = "修改用户（display_name/email/department_id/is_admin/status）。"
    required_permission = "user:manage"
    parameters = {
        "type": "object",
        "properties": {"user_id": {"type": "integer"}, "display_name": {"type": "string"},
                       "email": {"type": "string"}, "department_id": {"type": "integer"},
                       "is_admin": {"type": "boolean"}, "status": {"type": "string"}},
        "required": ["user_id"],
    }

    def summarize(self, args: dict) -> str:
        return f"修改用户 #{args.get('user_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import User

        u = await ctx.db.get(User, int(args.get("user_id") or 0))
        if not u or u.tenant_id != ctx.tenant_id:
            return ToolResult(content="用户不存在", is_error=True)
        for f in ("display_name", "email", "department_id", "is_admin", "status"):
            if args.get(f) is not None:
                setattr(u, f, args[f])
        await ctx.db.flush()
        return ToolResult(content=f"已更新用户 #{u.id}")


class CreateRoleTool(WriteToolMixin):
    name = "create_role"
    description = "创建角色（code/name/scope/description）。"
    required_permission = "role:manage"
    parameters = {
        "type": "object",
        "properties": {"code": {"type": "string"}, "name": {"type": "string"},
                       "scope": {"type": "string", "default": "tenant"}, "description": {"type": "string"}},
        "required": ["code", "name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建角色「{args.get('name')}」({args.get('code')})"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Role

        code = str(args.get("code") or "").strip()
        if not code:
            return ToolResult(content="角色 code 不能为空", is_error=True)
        r = Role(tenant_id=ctx.tenant_id, code=code, name=str(args.get("name") or code),
                 scope=str(args.get("scope") or "tenant"), description=args.get("description"))
        ctx.db.add(r)
        await ctx.db.flush()
        return ToolResult(content=f"已创建角色 #{r.id}「{r.name}」", data={"id": r.id})


class SetRolePermissionsTool(WriteToolMixin):
    name = "set_role_permissions"
    description = "设置角色的权限码集合（覆盖式）。先用 list_permissions 或 list_roles 获取 code。"
    required_permission = "role:manage"
    parameters = {
        "type": "object",
        "properties": {"role_id": {"type": "integer"},
                       "permission_codes": {"type": "array", "items": {"type": "string"}}},
        "required": ["role_id", "permission_codes"],
    }

    def summarize(self, args: dict) -> str:
        return f"设置角色 #{args.get('role_id')} 的权限（{len(args.get('permission_codes') or [])} 项）"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Permission, Role, RolePermission

        role = await ctx.db.get(Role, int(args.get("role_id") or 0))
        if not role:
            return ToolResult(content="角色不存在", is_error=True)
        codes = [str(c) for c in (args.get("permission_codes") or [])]
        perms = (await ctx.db.execute(select(Permission).where(Permission.code.in_(codes)))).scalars().all()
        await ctx.db.execute(_delete(RolePermission).where(RolePermission.role_id == role.id))
        for p in perms:
            ctx.db.add(RolePermission(role_id=role.id, permission_id=p.id))
        await ctx.db.flush()
        return ToolResult(content=f"已设置角色 #{role.id} 权限（{len(perms)} 项）")


class CreateDeptTool(WriteToolMixin):
    name = "create_dept"
    description = "创建部门（name/parent_id/code）。"
    required_permission = "dept:manage"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "parent_id": {"type": "integer"},
                       "code": {"type": "string"}},
        "required": ["name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建部门「{args.get('name')}」"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Department

        d = Department(tenant_id=ctx.tenant_id, name=str(args.get("name") or "新部门"),
                       parent_id=args.get("parent_id"), code=args.get("code"), path="", depth=0)
        ctx.db.add(d)
        await ctx.db.flush()
        d.path = f"{d.id}."
        await ctx.db.flush()
        return ToolResult(content=f"已创建部门 #{d.id}「{d.name}」", data={"id": d.id})


class CreateGroupTool(WriteToolMixin):
    name = "create_group"
    description = "创建用户组（name/description）。"
    required_permission = "group:manage"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
        "required": ["name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建用户组「{args.get('name')}」"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import UserGroup

        g = UserGroup(tenant_id=ctx.tenant_id, name=str(args.get("name") or "新用户组"),
                      description=args.get("description"))
        ctx.db.add(g)
        await ctx.db.flush()
        return ToolResult(content=f"已创建用户组 #{g.id}「{g.name}」", data={"id": g.id})


class GrantUserRoleTool(WriteToolMixin):
    name = "grant_user_role"
    description = "给用户授予角色（user_id/role_id/scope_type/scope_id）。"
    required_permission = "user:manage"
    parameters = {
        "type": "object",
        "properties": {"user_id": {"type": "integer"}, "role_id": {"type": "integer"},
                       "scope_type": {"type": "string", "default": "tenant"},
                       "scope_id": {"type": "integer", "default": 0}},
        "required": ["user_id", "role_id"],
    }

    def summarize(self, args: dict) -> str:
        return f"给用户 #{args.get('user_id')} 授予角色 #{args.get('role_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import UserRole

        ur = UserRole(tenant_id=ctx.tenant_id, user_id=int(args.get("user_id") or 0),
                      role_id=int(args.get("role_id") or 0),
                      scope_type=str(args.get("scope_type") or "tenant"),
                      scope_id=int(args.get("scope_id") or 0), granted_by=ctx.user_id)
        ctx.db.add(ur)
        await ctx.db.flush()
        return ToolResult(content=f"已授予角色 #{ur.role_id} 给用户 #{ur.user_id}")


# ==================== 知识库 ====================
class CreateKbTool(WriteToolMixin):
    name = "create_kb"
    description = "创建知识库（name/description/visibility）。"
    required_permission = "kb:create"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                       "visibility": {"type": "string", "enum": ["public", "internal", "private"], "default": "internal"}},
        "required": ["name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建知识库「{args.get('name')}」（{args.get('visibility', 'internal')}）"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import KBMember, KnowledgeBase
        from app.services.permission import user_principal

        kb = KnowledgeBase(tenant_id=ctx.tenant_id, name=str(args.get("name") or "新知识库"),
                           description=args.get("description"),
                           visibility=str(args.get("visibility") or "internal"), owner_id=ctx.user_id)
        ctx.db.add(kb)
        await ctx.db.flush()
        ctx.db.add(KBMember(tenant_id=ctx.tenant_id, kb_id=kb.id,
                            principal_id=user_principal(ctx.user_id), perm_level="manager",
                            granted_by=ctx.user_id))
        await ctx.db.flush()
        return ToolResult(content=f"已创建知识库 #{kb.id}「{kb.name}」", data={"id": kb.id})


class DeleteKbTool(WriteToolMixin):
    name = "delete_kb"
    description = "删除知识库（软删除）。"
    required_permission = "kb:delete"
    dangerous = True
    parameters = {"type": "object", "properties": {"kb_id": {"type": "integer"}}, "required": ["kb_id"]}

    def summarize(self, args: dict) -> str:
        return f"删除知识库 #{args.get('kb_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import KnowledgeBase

        kb = await ctx.db.get(KnowledgeBase, int(args.get("kb_id") or 0))
        if not kb or kb.tenant_id != ctx.tenant_id:
            return ToolResult(content="知识库不存在", is_error=True)
        kb.status = "deleted"
        await ctx.db.flush()
        return ToolResult(content=f"已删除知识库 #{kb.id}")


class RemoveKbMemberTool(WriteToolMixin):
    name = "remove_kb_member"
    description = "移除知识库成员（member_id，用 list_kb_members 查）。"
    required_permission = "kb:member_manage"
    parameters = {
        "type": "object",
        "properties": {"kb_id": {"type": "integer"}, "member_id": {"type": "integer"}},
        "required": ["kb_id", "member_id"],
    }

    def summarize(self, args: dict) -> str:
        return f"移除知识库 #{args.get('kb_id')} 的成员 #{args.get('member_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import KBMember

        m = await ctx.db.get(KBMember, int(args.get("member_id") or 0))
        if not m or m.kb_id != int(args.get("kb_id") or 0):
            return ToolResult(content="成员不存在", is_error=True)
        await ctx.db.delete(m)
        await ctx.db.flush()
        return ToolResult(content="已移除成员")


# ==================== 智能体 ====================
class UpdateAgentTool(WriteToolMixin):
    name = "update_agent"
    description = "修改智能体（name/description/system_prompt/status 等）。"
    required_permission = "agent:edit"
    parameters = {
        "type": "object",
        "properties": {"agent_id": {"type": "integer"}, "name": {"type": "string"},
                       "description": {"type": "string"}, "system_prompt": {"type": "string"}},
        "required": ["agent_id"],
    }

    def summarize(self, args: dict) -> str:
        return f"修改智能体 #{args.get('agent_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Agent

        a = await ctx.db.get(Agent, int(args.get("agent_id") or 0))
        if not a or a.tenant_id != ctx.tenant_id:
            return ToolResult(content="智能体不存在", is_error=True)
        for f in ("name", "description", "system_prompt"):
            if args.get(f) is not None:
                setattr(a, f, args[f])
        await ctx.db.flush()
        return ToolResult(content=f"已更新智能体 #{a.id}")


class PublishAgentTool(WriteToolMixin):
    name = "publish_agent"
    description = "发布智能体（使其可用）。"
    required_permission = "agent:edit"
    parameters = {"type": "object", "properties": {"agent_id": {"type": "integer"}}, "required": ["agent_id"]}

    def summarize(self, args: dict) -> str:
        return f"发布智能体 #{args.get('agent_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        import time as _t

        from app.models import Agent

        a = await ctx.db.get(Agent, int(args.get("agent_id") or 0))
        if not a or a.tenant_id != ctx.tenant_id:
            return ToolResult(content="智能体不存在", is_error=True)
        a.status = "active"
        a.published_at = int(_t.time() * 1000)
        await ctx.db.flush()
        return ToolResult(content=f"已发布智能体 #{a.id}")


class DeleteAgentTool(WriteToolMixin):
    name = "delete_agent"
    description = "删除智能体（软删除）。"
    required_permission = "agent:edit"
    dangerous = True
    parameters = {"type": "object", "properties": {"agent_id": {"type": "integer"}}, "required": ["agent_id"]}

    def summarize(self, args: dict) -> str:
        return f"删除智能体 #{args.get('agent_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Agent

        a = await ctx.db.get(Agent, int(args.get("agent_id") or 0))
        if not a or a.tenant_id != ctx.tenant_id:
            return ToolResult(content="智能体不存在", is_error=True)
        a.status = "deleted"
        await ctx.db.flush()
        return ToolResult(content=f"已删除智能体 #{a.id}")


# ==================== API Key ====================
class CreateApiKeyTool(WriteToolMixin):
    name = "create_api_key"
    description = "创建 API 密钥（name/scopes/kb_ids/rate_limit）。明文只返回一次，请妥善保存。"
    required_permission = "apikey:manage"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"},
                       "scopes": {"type": "array", "items": {"type": "string"}},
                       "kb_ids": {"type": "array", "items": {"type": "integer"}},
                       "rate_limit": {"type": "integer", "default": 60}},
        "required": ["name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建 API 密钥「{args.get('name')}」"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        import secrets

        from app.models import ApiKey
        from app.services.api_key_service import hash_key

        plain = "sk-" + secrets.token_urlsafe(32)
        k = ApiKey(tenant_id=ctx.tenant_id, user_id=ctx.user_id, name=str(args.get("name") or "AI 创建"),
                   key_prefix=plain[:12], key_hash=hash_key(plain),
                   scopes=args.get("scopes") or ["chat:use"], kb_ids=args.get("kb_ids"),
                   rate_limit=int(args.get("rate_limit") or 60))
        ctx.db.add(k)
        await ctx.db.flush()
        return ToolResult(content=f"已创建 API 密钥（明文，仅显示一次）：{plain}", data={"id": k.id, "key": plain})


class RevokeApiKeyTool(WriteToolMixin):
    name = "revoke_api_key"
    description = "吊销 API 密钥（key_id）。"
    required_permission = "apikey:manage"
    dangerous = True
    parameters = {"type": "object", "properties": {"key_id": {"type": "integer"}}, "required": ["key_id"]}

    def summarize(self, args: dict) -> str:
        return f"吊销 API 密钥 #{args.get('key_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ApiKey

        k = await ctx.db.get(ApiKey, int(args.get("key_id") or 0))
        if not k or k.tenant_id != ctx.tenant_id:
            return ToolResult(content="密钥不存在", is_error=True)
        k.status = "revoked"
        await ctx.db.flush()
        return ToolResult(content=f"已吊销密钥 #{k.id}")


# ==================== 文档批量与 ACL ====================
class BatchDeleteDocumentsTool(WriteToolMixin):
    name = "batch_delete_documents"
    description = "批量删除文档（ids 数组）。"
    required_permission = "doc:delete"
    dangerous = True
    parameters = {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["ids"]}

    def summarize(self, args: dict) -> str:
        return f"批量删除 {len(args.get('ids') or [])} 个文档"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Chunk, Document

        ids = [int(i) for i in (args.get("ids") or [])][:500]
        rows = (await ctx.db.execute(
            select(Document).where(Document.id.in_(ids), Document.tenant_id == ctx.tenant_id)
        )).scalars().all()
        for d in rows:
            await ctx.db.execute(_delete(Chunk).where(Chunk.doc_id == d.id))
            await ctx.db.delete(d)
        await ctx.db.flush()
        return ToolResult(content=f"已删除 {len(rows)} 个文档")


class BatchMoveDocumentsTool(WriteToolMixin):
    name = "batch_move_documents"
    description = "批量移动文档到文件夹（ids / folder_id，folder_id 为空=根目录）。"
    required_permission = "doc:update"
    parameters = {
        "type": "object",
        "properties": {"ids": {"type": "array", "items": {"type": "integer"}},
                       "folder_id": {"type": "integer"}},
        "required": ["ids"],
    }

    def summarize(self, args: dict) -> str:
        return f"批量移动 {len(args.get('ids') or [])} 个文档到文件夹 {args.get('folder_id') or '根目录'}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Document

        ids = [int(i) for i in (args.get("ids") or [])][:500]
        rows = (await ctx.db.execute(
            select(Document).where(Document.id.in_(ids), Document.tenant_id == ctx.tenant_id)
        )).scalars().all()
        for d in rows:
            d.folder_id = args.get("folder_id")
        await ctx.db.flush()
        return ToolResult(content=f"已移动 {len(rows)} 个文档")


class SetDocVisibilityTool(WriteToolMixin):
    name = "set_doc_visibility"
    description = "设置文档可见性（inherit/public/restricted）。"
    required_permission = "doc:acl_manage"
    parameters = {
        "type": "object",
        "properties": {"doc_id": {"type": "integer"},
                       "visibility": {"type": "string", "enum": ["inherit", "public", "restricted"]}},
        "required": ["doc_id", "visibility"],
    }

    def summarize(self, args: dict) -> str:
        return f"设置文档 #{args.get('doc_id')} 可见性为 {args.get('visibility')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Document

        d = await ctx.db.get(Document, int(args.get("doc_id") or 0))
        if not d or d.tenant_id != ctx.tenant_id:
            return ToolResult(content="文档不存在", is_error=True)
        d.visibility = str(args.get("visibility"))
        await ctx.db.flush()
        return ToolResult(content=f"已设置文档 #{d.id} 可见性")


class ReprocessDocumentTool(WriteToolMixin):
    name = "reprocess_document"
    description = "重新处理（重灌）文档。"
    required_permission = "doc:update"
    parameters = {"type": "object", "properties": {"doc_id": {"type": "integer"}}, "required": ["doc_id"]}

    def summarize(self, args: dict) -> str:
        return f"重新处理文档 #{args.get('doc_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Document
        from app.tasks.ingest_tasks import enqueue_document

        d = await ctx.db.get(Document, int(args.get("doc_id") or 0))
        if not d or d.tenant_id != ctx.tenant_id:
            return ToolResult(content="文档不存在", is_error=True)
        d.status = "pending"; d.progress = 0; d.error_msg = None
        await ctx.db.flush()
        await enqueue_document(d.id)
        return ToolResult(content=f"已重新提交文档 #{d.id}")


class UpdateDocumentTagsTool(WriteToolMixin):
    name = "update_document_tags"
    description = "设置文档标签（doc_id / tags 字符串数组）。"
    required_permission = "doc:update"
    parameters = {
        "type": "object",
        "properties": {"doc_id": {"type": "integer"},
                       "tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["doc_id", "tags"],
    }

    def summarize(self, args: dict) -> str:
        return f"设置文档 #{args.get('doc_id')} 标签：{args.get('tags')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Document

        d = await ctx.db.get(Document, int(args.get("doc_id") or 0))
        if not d or d.tenant_id != ctx.tenant_id:
            return ToolResult(content="文档不存在", is_error=True)
        seen = []
        for t in (args.get("tags") or []):
            t = str(t).strip()
            if t and t not in seen and len(t) <= 32:
                seen.append(t)
        d.tags = seen[:20]
        await ctx.db.flush()
        return ToolResult(content=f"已更新文档 #{d.id} 标签")


# ==================== 外部渠道 ====================
class CreateChannelTool(WriteToolMixin):
    name = "create_channel"
    description = ("创建外部渠道（kind=qqbot/wxclaw/wework/feishu，name，config 依渠道而定，"
                   "reply_mode=rag/agent，kb_mode=auto/custom/off）。微信需先扫码建议在页面配置。")
    required_permission = "channel:manage"
    parameters = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["qqbot", "wxclaw", "wework", "feishu"]},
            "name": {"type": "string"}, "config": {"type": "object"},
            "reply_mode": {"type": "string", "default": "rag"},
            "kb_mode": {"type": "string", "default": "auto"},
            "default_kb_ids": {"type": "array", "items": {"type": "integer"}},
            "enabled": {"type": "boolean", "default": True},
        }, "required": ["kind", "name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建 {args.get('kind')} 渠道「{args.get('name')}」"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Channel
        from app.services.channel_service import encrypt_config

        c = Channel(tenant_id=ctx.tenant_id, kind=str(args.get("kind")), name=str(args.get("name")),
                    config=encrypt_config(args.get("config") or {}),
                    enabled=bool(args.get("enabled", True)),
                    default_tenant_id=ctx.tenant_id,
                    default_kb_ids=args.get("default_kb_ids"),
                    reply_mode=str(args.get("reply_mode") or "rag"),
                    kb_mode=str(args.get("kb_mode") or "auto"))
        ctx.db.add(c)
        await ctx.db.flush()
        return ToolResult(content=f"已创建渠道 #{c.id}「{c.name}」", data={"id": c.id})


class DeleteChannelTool(WriteToolMixin):
    name = "delete_channel"
    description = "删除外部渠道。"
    required_permission = "channel:manage"
    dangerous = True
    parameters = {"type": "object", "properties": {"channel_id": {"type": "integer"}}, "required": ["channel_id"]}

    def summarize(self, args: dict) -> str:
        return f"删除渠道 #{args.get('channel_id')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Channel

        c = await ctx.db.get(Channel, int(args.get("channel_id") or 0))
        if not c or c.tenant_id != ctx.tenant_id:
            return ToolResult(content="渠道不存在", is_error=True)
        c.status = "deleted"; c.enabled = False
        await ctx.db.flush()
        return ToolResult(content=f"已删除渠道 #{c.id}")


# ==================== 工作流 ====================
class SaveWorkflowTool(WriteToolMixin):
    name = "save_workflow"
    description = "保存工作流编排（agent_id + graph 图定义）。graph 结构复杂，建议在页面编辑。"
    required_permission = "workflow:edit"
    parameters = {
        "type": "object",
        "properties": {"agent_id": {"type": "integer"}, "graph": {"type": "object"},
                       "name": {"type": "string"}},
        "required": ["agent_id", "graph"],
    }

    def summarize(self, args: dict) -> str:
        return f"保存智能体 #{args.get('agent_id')} 的工作流"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Workflow

        wf = (await ctx.db.execute(
            select(Workflow).where(Workflow.agent_id == int(args.get("agent_id") or 0))
        )).scalars().first()
        if wf:
            wf.graph = args.get("graph")
            if args.get("name"):
                wf.name = args["name"]
        else:
            wf = Workflow(tenant_id=ctx.tenant_id, agent_id=int(args.get("agent_id") or 0),
                          name=str(args.get("name") or "工作流"), graph=args.get("graph"))
            ctx.db.add(wf)
        await ctx.db.flush()
        return ToolResult(content=f"已保存工作流 #{wf.id}", data={"id": wf.id})


# ==================== 模型配置 ====================
class CreateModelConfigTool(WriteToolMixin):
    name = "create_model_config"
    description = "创建模型配置（provider_id/purpose/model_name/embedding_dim）。需先有 Provider。"
    required_permission = "model:manage"
    parameters = {
        "type": "object",
        "properties": {"provider_id": {"type": "integer"},
                       "purpose": {"type": "string", "enum": ["chat", "embedding", "rerank"]},
                       "model_name": {"type": "string"}, "display_name": {"type": "string"},
                       "embedding_dim": {"type": "integer"}},
        "required": ["provider_id", "purpose", "model_name"],
    }

    def summarize(self, args: dict) -> str:
        return f"创建模型配置 {args.get('purpose')}/{args.get('model_name')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ModelConfig

        mc = ModelConfig(tenant_id=ctx.tenant_id, provider_id=int(args.get("provider_id") or 0),
                         purpose=str(args.get("purpose")), model_name=str(args.get("model_name")),
                         display_name=str(args.get("display_name") or args.get("model_name")),
                         embedding_dim=args.get("embedding_dim"))
        ctx.db.add(mc)
        await ctx.db.flush()
        return ToolResult(content=f"已创建模型配置 #{mc.id}", data={"id": mc.id})


OPS_TOOLS = [
    CreateScheduledTaskTool(), UpdateScheduledTaskTool(), DeleteScheduledTaskTool(), RunScheduledTaskNowTool(),
    CreateUserTool(), UpdateUserTool(), CreateRoleTool(), SetRolePermissionsTool(),
    CreateDeptTool(), CreateGroupTool(), GrantUserRoleTool(),
    CreateKbTool(), DeleteKbTool(), RemoveKbMemberTool(),
    UpdateAgentTool(), PublishAgentTool(), DeleteAgentTool(),
    CreateApiKeyTool(), RevokeApiKeyTool(),
    BatchDeleteDocumentsTool(), BatchMoveDocumentsTool(), SetDocVisibilityTool(),
    ReprocessDocumentTool(), UpdateDocumentTagsTool(),
    CreateChannelTool(), DeleteChannelTool(),
    SaveWorkflowTool(), CreateModelConfigTool(),
]
