"""AI 操作工具（第三轮）：补齐此前无 AI 入口的功能模块。

覆盖：待办/提醒、录单模板、客服话术库、渠道身份绑定、站内通知、问答评测、会话管理。
设计沿用 manage_* 的 action 型合并，避免工具爆炸；写操作经 HITL 确认。
"""
from __future__ import annotations

import time

from sqlalchemy import select

from app.agents.tools.base import ToolContext, ToolResult, WriteToolMixin


def _ms(v) -> int | None:
    """把用户给的时间转成毫秒时间戳。支持 int(ms/秒自动判别)、ISO8601 字符串。"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        n = int(v)
        return n * 1000 if n < 10_000_000_000 else n  # <1e10 视为秒
    try:
        from datetime import datetime

        s = str(v).strip().replace("/", "-").replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp() * 1000)
    except Exception:  # noqa: BLE001
        return None


def _fmt_ts(ms) -> str:
    if not ms:
        return "-"
    try:
        from datetime import datetime

        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(ms)


# ==================== 待办 / 提醒 ====================
class ManageReminderTool(WriteToolMixin):
    name = "manage_reminder"
    description = (
        "管理待办/日程/提醒（用户在「待办日程」页看到的内容）。\n"
        "action=list 列出（可按 status=pending/done 过滤）；create 新建（title 必填）；"
        "update 修改；done 标记完成；delete 删除。\n"
        "due_at 给「到期时间」：可传 ISO 字符串（如 2026-10-20 09:00）或毫秒/秒时间戳；"
        "repeat_cron 设重复（如 '0 9 * * *' 每天 9 点）；remind_before_minutes 提前提醒。\n"
        "「X 分钟后提醒我」可传 due_at=当前+分钟数。适合个人待办，非团队定时任务。"
    )
    required_permission = "chat:use"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "create", "update", "done", "delete"]},
            "reminder_id": {"type": "integer", "description": "update/done/delete 需要"},
            "title": {"type": "string", "description": "待办标题"},
            "content": {"type": "string", "description": "详细内容"},
            "due_at": {"type": "string", "description": "到期时间：ISO 字符串或时间戳"},
            "assignee_id": {"type": "integer", "description": "负责人 user_id（默认自己）"},
            "repeat_cron": {"type": "string", "description": "重复 cron，如 0 9 * * *"},
            "remind_before_minutes": {"type": "integer", "description": "提前多少分钟提醒"},
            "status": {"type": "string", "enum": ["pending", "done"], "description": "list 过滤"},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        a = args.get("action")
        label = {"list": "列出待办", "create": f"新建待办「{args.get('title')}」",
                 "update": f"修改待办 #{args.get('reminder_id')}",
                 "done": f"完成待办 #{args.get('reminder_id')}",
                 "delete": f"删除待办 #{args.get('reminder_id')}"}
        return label.get(a, f"待办操作 {a}")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Reminder
        from app.services import reminder_service as S

        action = str(args.get("action") or "")
        if action == "list":
            rows = await S.list_reminders(
                ctx.db, tenant_id=ctx.tenant_id,
                assignee_id=args.get("assignee_id"),
                status=args.get("status"),
            )
            if not rows:
                return ToolResult(content="（暂无待办）", data={"count": 0})
            lines = [f"共 {len(rows)} 条待办："]
            for r in rows:
                flag = "✓" if r.status == "done" else "○"
                lines.append(f"  [{r.id}] {flag} {r.title}｜到期 {_fmt_ts(r.due_at)}"
                             + (f"｜重复 {r.repeat_cron}" if r.repeat_cron else ""))
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "create":
            if not args.get("title"):
                return ToolResult(content="新建待办需提供 title", is_error=True)
            r = await S.create_reminder(
                ctx.db, tenant_id=ctx.tenant_id, creator_id=ctx.user_id,
                data={"title": args["title"], "content": args.get("content"),
                      "due_at": _ms(args.get("due_at")),
                      "assignee_id": args.get("assignee_id"),
                      "repeat_cron": args.get("repeat_cron"),
                      "remind_before_minutes": args.get("remind_before_minutes") or 0},
            )
            await ctx.db.flush()
            return ToolResult(content=f"已创建待办 #{r.id}「{r.title}」（到期 {_fmt_ts(r.due_at)}）",
                              data={"reminder_id": r.id})

        rid = args.get("reminder_id")
        if not rid:
            return ToolResult(content=f"{action} 需要 reminder_id", is_error=True)
        r = await ctx.db.get(Reminder, int(rid))
        if not r or r.tenant_id != ctx.tenant_id:
            return ToolResult(content="待办不存在", is_error=True)

        if action == "update":
            data: dict = {}
            for k in ("title", "content", "repeat_cron", "remind_before_minutes"):
                if k in args and args[k] is not None:
                    data[k] = args[k]
            if args.get("due_at") is not None:
                data["due_at"] = _ms(args.get("due_at"))
            if args.get("assignee_id") is not None:
                data["assignee_id"] = args["assignee_id"]
            if args.get("status"):
                data["status"] = args["status"]
            await S.update_reminder(ctx.db, r, data)
            await ctx.db.flush()
            return ToolResult(content=f"已更新待办 #{r.id}")
        if action == "done":
            await S.mark_done(ctx.db, r)
            await ctx.db.flush()
            return ToolResult(content=f"已完成待办 #{r.id}「{r.title}」")
        if action == "delete":
            await ctx.db.delete(r)
            await ctx.db.flush()
            return ToolResult(content=f"已删除待办 #{r.id}")
        return ToolResult(content=f"不支持的操作：{action}", is_error=True)


# ==================== 录单模板 ====================
class ManageRecordTemplateTool(WriteToolMixin):
    name = "manage_record_template"
    description = (
        "管理「智能录单」模板（定义要从通话记录/聊天/邮件里抽取哪些字段）。\n"
        "action=list 列出模板；create 新建（name + fields）；update 修改；delete 删除；"
        "list_entries 查看某模板已抽取的台账记录；export 导出记录为 CSV（返回文本）。\n"
        "fields 是字段定义数组：[{name(键名), label(显示名), type(text|number|date|phone|enum), "
        "required(bool), desc, options(enum 选项)}]。\n"
        "抽文本 → 台账用 extract_records 工具（需先有模板）。"
    )
    required_permission = "record:manage"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list", "create", "update", "delete", "list_entries", "export"]},
            "template_id": {"type": "integer"},
            "name": {"type": "string", "description": "模板名"},
            "description": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "object"},
                       "description": "字段定义数组"},
            "instructions": {"type": "string", "description": "抽取的额外业务提示"},
            "enabled": {"type": "boolean"},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        return {"list": "列出录单模板", "create": f"新建录单模板「{args.get('name')}」",
                "update": f"修改录单模板 #{args.get('template_id')}",
                "delete": f"删除录单模板 #{args.get('template_id')}",
                "list_entries": f"查看模板 #{args.get('template_id')} 的录单记录",
                "export": f"导出模板 #{args.get('template_id')} 记录"}.get(
                    str(args.get("action")), "录单模板操作")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import RecordEntry, RecordTemplate

        action = str(args.get("action") or "")
        if action == "list":
            rows = (await ctx.db.execute(
                select(RecordTemplate).where(RecordTemplate.tenant_id == ctx.tenant_id)
                .order_by(RecordTemplate.id.desc())
            )).scalars().all()
            if not rows:
                return ToolResult(content="（暂无录单模板）", data={"count": 0})
            lines = [f"共 {len(rows)} 个模板："]
            for t in rows:
                fld = ", ".join(str(f.get("label") or f.get("name")) for f in (t.fields or [])[:8])
                lines.append(f"  [{t.id}] {t.name}（{'启用' if t.enabled else '停用'}）字段：{fld}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "create":
            if not args.get("name") or not args.get("fields"):
                return ToolResult(content="新建模板需提供 name 与 fields", is_error=True)
            t = RecordTemplate(
                tenant_id=ctx.tenant_id, name=str(args["name"])[:128],
                description=args.get("description"), fields=args.get("fields"),
                instructions=args.get("instructions"),
                enabled=bool(args.get("enabled", True)), created_by=ctx.user_id,
            )
            ctx.db.add(t)
            await ctx.db.flush()
            return ToolResult(content=f"已创建录单模板 #{t.id}「{t.name}」", data={"template_id": t.id})

        tid = args.get("template_id")
        if not tid:
            return ToolResult(content=f"{action} 需要 template_id", is_error=True)
        t = await ctx.db.get(RecordTemplate, int(tid))
        if not t or t.tenant_id != ctx.tenant_id:
            return ToolResult(content="模板不存在", is_error=True)

        if action == "update":
            for k in ("name", "description", "fields", "instructions"):
                if args.get(k) is not None:
                    setattr(t, k, args[k])
            if args.get("enabled") is not None:
                t.enabled = bool(args["enabled"])
            await ctx.db.flush()
            return ToolResult(content=f"已更新录单模板 #{t.id}")
        if action == "delete":
            await ctx.db.delete(t)
            await ctx.db.flush()
            return ToolResult(content=f"已删除录单模板 #{t.id}")

        # list_entries / export
        entries = (await ctx.db.execute(
            select(RecordEntry).where(
                RecordEntry.template_id == t.id, RecordEntry.tenant_id == ctx.tenant_id
            ).order_by(RecordEntry.id.desc()).limit(500)
        )).scalars().all()
        if not entries:
            return ToolResult(content="该模板暂无录单记录", data={"count": 0})
        headers = [str(f.get("name")) for f in (t.fields or [])]
        labels = [str(f.get("label") or f.get("name")) for f in (t.fields or [])]
        if action == "export":
            import csv
            import io

            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(labels)
            for e in entries:
                d = e.data or {}
                w.writerow([str(d.get(h, "")) for h in headers])
            return ToolResult(content=buf.getvalue()[:20000],
                              data={"count": len(entries), "format": "csv"})
        lines = [f"模板「{t.name}」共 {len(entries)} 条记录（最近 {min(len(entries), 20)} 条）："]
        for e in entries[:20]:
            d = e.data or {}
            lines.append("  " + " | ".join(f"{lb}={d.get(h, '')}" for h, lb in zip(headers, labels)))
        return ToolResult(content="\n".join(lines), data={"count": len(entries)})


# ==================== 客服话术库 ====================
class ManageQuickReplyTool(WriteToolMixin):
    name = "manage_quick_reply"
    description = (
        "管理客服话术库（快捷回复模板，客服工单界面选用）。\n"
        "action=list 列出；create 新建（title + content）；update 修改；delete 删除。\n"
        "category 分类（可选），scope 适用范围（可选）。"
    )
    required_permission = "service:manage"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "create", "update", "delete"]},
            "quick_reply_id": {"type": "integer"},
            "title": {"type": "string", "description": "话术标题"},
            "content": {"type": "string", "description": "话术正文"},
            "category": {"type": "string"},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        return {"list": "列出话术库", "create": f"新建话术「{args.get('title')}」",
                "update": f"修改话术 #{args.get('quick_reply_id')}",
                "delete": f"删除话术 #{args.get('quick_reply_id')}"}.get(
                    str(args.get("action")), "话术库操作")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ServiceTicketQuickReply

        action = str(args.get("action") or "")
        if action == "list":
            rows = (await ctx.db.execute(
                select(ServiceTicketQuickReply).where(
                    ServiceTicketQuickReply.tenant_id == ctx.tenant_id
                ).order_by(ServiceTicketQuickReply.id.desc())
            )).scalars().all()
            if not rows:
                return ToolResult(content="（暂无话术）", data={"count": 0})
            lines = [f"共 {len(rows)} 条话术："]
            for r in rows:
                lines.append(f"  [{r.id}] {r.title}"
                             + (f"（{r.category}）" if r.category else "")
                             + f"｜{str(r.content or '')[:40]}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "create":
            if not args.get("title") or not args.get("content"):
                return ToolResult(content="新建话术需提供 title 与 content", is_error=True)
            r = ServiceTicketQuickReply(
                tenant_id=ctx.tenant_id, title=str(args["title"])[:128],
                content=str(args["content"]), category=args.get("category"),
                enabled=True, created_by=ctx.user_id,
            )
            ctx.db.add(r)
            await ctx.db.flush()
            return ToolResult(content=f"已创建话术 #{r.id}「{r.title}」", data={"quick_reply_id": r.id})

        qid = args.get("quick_reply_id")
        if not qid:
            return ToolResult(content=f"{action} 需要 quick_reply_id", is_error=True)
        r = await ctx.db.get(ServiceTicketQuickReply, int(qid))
        if not r or r.tenant_id != ctx.tenant_id:
            return ToolResult(content="话术不存在", is_error=True)
        if action == "update":
            for k in ("title", "content", "category"):
                if args.get(k) is not None:
                    setattr(r, k, args[k])
            await ctx.db.flush()
            return ToolResult(content=f"已更新话术 #{r.id}")
        if action == "delete":
            await ctx.db.delete(r)
            await ctx.db.flush()
            return ToolResult(content=f"已删除话术 #{r.id}")
        return ToolResult(content=f"不支持的操作：{action}", is_error=True)


# ==================== 渠道身份绑定 ====================
class ManageChannelUserTool(WriteToolMixin):
    name = "manage_channel_user"
    description = (
        "管理外部渠道身份（QQ/微信/企微/飞书 用户）与其内部账号的绑定关系。\n"
        "绑定后，该外部身份在渠道里继承内部账号的权限（未绑定则只读）。\n"
        "action=list 列出渠道用户（可按 channel 过滤）；bind 绑定（channel_user_id + user_id）；"
        "unbind 解绑；set_note 写内部备注（仅客服可见）。\n"
        "拿到 channel_user_id 需先 list。"
    )
    required_permission = "channel:manage"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "bind", "unbind", "set_note"]},
            "channel_user_id": {"type": "integer"},
            "user_id": {"type": "integer", "description": "绑定的内部账号 user_id"},
            "channel": {"type": "string", "description": "list 过滤：qqbot/wxclaw/wework/feishu"},
            "note": {"type": "string", "description": "内部备注"},
            "limit": {"type": "integer", "default": 50},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        return {"list": "列出渠道身份", "bind": f"绑定渠道身份 #{args.get('channel_user_id')} → 用户 #{args.get('user_id')}",
                "unbind": f"解绑渠道身份 #{args.get('channel_user_id')}",
                "set_note": f"设置渠道备注 #{args.get('channel_user_id')}"}.get(
                    str(args.get("action")), "渠道身份操作")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import ChannelUser, User

        action = str(args.get("action") or "")
        if action == "list":
            q = select(ChannelUser).where(ChannelUser.tenant_id == ctx.tenant_id)
            if args.get("channel"):
                q = q.where(ChannelUser.channel == str(args["channel"]))
            rows = (await ctx.db.execute(
                q.order_by(ChannelUser.id.desc()).limit(int(args.get("limit") or 50))
            )).scalars().all()
            if not rows:
                return ToolResult(content="（暂无渠道身份）", data={"count": 0})
            lines = [f"共 {len(rows)} 条："]
            for c in rows:
                bind = f"→用户#{c.bound_user_id}" if c.bound_user_id else "（未绑定，只读）"
                lines.append(f"  [{c.id}] {c.channel}:{c.external_id} {c.display_name or ''} {bind}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        cid = args.get("channel_user_id")
        if not cid:
            return ToolResult(content=f"{action} 需要 channel_user_id", is_error=True)
        cu = await ctx.db.get(ChannelUser, int(cid))
        if not cu or cu.tenant_id != ctx.tenant_id:
            return ToolResult(content="渠道身份不存在", is_error=True)

        if action == "bind":
            uid = args.get("user_id")
            if not uid:
                return ToolResult(content="bind 需要 user_id", is_error=True)
            u = await ctx.db.get(User, int(uid))
            if not u or u.tenant_id != ctx.tenant_id:
                return ToolResult(content="目标内部账号不存在", is_error=True)
            cu.bound_user_id = u.id
            cu.bind_code = None
            await ctx.db.flush()
            return ToolResult(content=f"已将 {cu.channel}:{cu.external_id} 绑定到「{u.username}」")
        if action == "unbind":
            cu.bound_user_id = None
            await ctx.db.flush()
            return ToolResult(content=f"已解绑 {cu.channel}:{cu.external_id}（恢复只读）")
        if action == "set_note":
            cu.note = args.get("note")
            await ctx.db.flush()
            return ToolResult(content="已更新内部备注")
        return ToolResult(content=f"不支持的操作：{action}", is_error=True)


# ==================== 站内通知 ====================
class ManageNotificationTool(WriteToolMixin):
    name = "manage_notification"
    description = (
        "站内通知（铃铛里的消息）。\n"
        "action=list 列出当前用户的通知（unread_only 只看未读）；"
        "send 给某用户发一条站内通知（user_id + title，body/level/link 可选）；"
        "read 标记单条已读；read_all 全部已读。\n"
        "level=info/success/warning/error。适合提醒自己或同事。"
    )
    required_permission = "notify:manage"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "send", "read", "read_all"]},
            "notification_id": {"type": "integer"},
            "user_id": {"type": "integer", "description": "send 的接收人"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "level": {"type": "string", "enum": ["info", "success", "warning", "error"]},
            "link": {"type": "string", "description": "点击跳转的前端路由，如 /agents"},
            "unread_only": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        return {"list": "列出站内通知", "send": f"给用户 #{args.get('user_id')} 发通知「{args.get('title')}」",
                "read": f"标记通知 #{args.get('notification_id')} 已读",
                "read_all": "全部标记已读"}.get(str(args.get("action")), "通知操作")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Notification, User

        action = str(args.get("action") or "")
        if action == "list":
            q = select(Notification).where(
                Notification.tenant_id == ctx.tenant_id, Notification.user_id == ctx.user_id
            )
            if args.get("unread_only"):
                q = q.where(Notification.read.is_(False))
            rows = (await ctx.db.execute(
                q.order_by(Notification.id.desc()).limit(int(args.get("limit") or 20))
            )).scalars().all()
            if not rows:
                return ToolResult(content="（暂无通知）", data={"count": 0})
            lines = [f"共 {len(rows)} 条："]
            for n in rows:
                flag = "●" if not n.read else "○"
                lines.append(f"  [{n.id}] {flag} [{n.level}] {n.title}｜{str(n.body or '')[:40]}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "send":
            uid = args.get("user_id")
            if not uid or not args.get("title"):
                return ToolResult(content="send 需要 user_id 与 title", is_error=True)
            u = await ctx.db.get(User, int(uid))
            if not u or u.tenant_id != ctx.tenant_id:
                return ToolResult(content="接收人不存在", is_error=True)
            n = Notification(
                tenant_id=ctx.tenant_id, user_id=u.id, kind="system",
                title=str(args["title"])[:256], body=args.get("body"),
                level=str(args.get("level") or "info"), link=args.get("link"),
                sender_id=ctx.user_id,
            )
            ctx.db.add(n)
            await ctx.db.flush()
            return ToolResult(content=f"已通知「{u.username}」：{n.title}", data={"notification_id": n.id})

        if action == "read_all":
            rows = (await ctx.db.execute(
                select(Notification).where(
                    Notification.tenant_id == ctx.tenant_id,
                    Notification.user_id == ctx.user_id,
                    Notification.read.is_(False),
                )
            )).scalars().all()
            for n in rows:
                n.read = True
            await ctx.db.flush()
            return ToolResult(content=f"已将 {len(rows)} 条通知标记为已读")

        nid = args.get("notification_id")
        if not nid:
            return ToolResult(content="read 需要 notification_id", is_error=True)
        n = await ctx.db.get(Notification, int(nid))
        if not n or n.tenant_id != ctx.tenant_id or n.user_id != ctx.user_id:
            return ToolResult(content="通知不存在", is_error=True)
        n.read = True
        await ctx.db.flush()
        return ToolResult(content=f"已标记通知 #{n.id} 已读")


# ==================== 问答评测 ====================
class ManageEvalTool(WriteToolMixin):
    name = "manage_eval"
    description = (
        "问答评测（评估回答质量/检索命中）。\n"
        "action=list_datasets 列数据集；create_dataset 建集（name，kb_ids 可选）；"
        "add_question 加题（dataset_id + question，expected_answer/expected_doc_ids 可选）；"
        "list_questions 列题；run 触发评测（dataset_id，异步）；get_run 查某次运行结果；"
        "list_runs 列某数据集的运行历史。\n"
        "评测会逐题召回+生成并按忠实度/相关性打分，适合调优知识库与提示词。"
    )
    required_permission = "eval:manage"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list_datasets", "create_dataset", "add_question", "list_questions",
                                "run", "get_run", "list_runs", "delete_dataset"]},
            "dataset_id": {"type": "integer"},
            "run_id": {"type": "integer"},
            "name": {"type": "string", "description": "数据集名"},
            "description": {"type": "string"},
            "kb_ids": {"type": "array", "items": {"type": "integer"}, "description": "评测检索的知识库"},
            "question": {"type": "string"},
            "expected_answer": {"type": "string"},
            "expected_doc_ids": {"type": "array", "items": {"type": "integer"}},
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        return {"list_datasets": "列出评测数据集", "create_dataset": f"新建评测集「{args.get('name')}」",
                "add_question": f"向评测集 #{args.get('dataset_id')} 加题",
                "list_questions": f"列出评测集 #{args.get('dataset_id')} 的题",
                "run": f"运行评测集 #{args.get('dataset_id')}",
                "get_run": f"查看评测运行 #{args.get('run_id')}",
                "list_runs": f"查看评测集 #{args.get('dataset_id')} 的运行历史",
                "delete_dataset": f"删除评测集 #{args.get('dataset_id')}"}.get(
                    str(args.get("action")), "评测操作")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import EvalDataset, EvalQuestion, EvalResult, EvalRun

        action = str(args.get("action") or "")
        if action == "list_datasets":
            rows = (await ctx.db.execute(
                select(EvalDataset).where(EvalDataset.tenant_id == ctx.tenant_id)
                .order_by(EvalDataset.id.desc())
            )).scalars().all()
            if not rows:
                return ToolResult(content="（暂无评测数据集）", data={"count": 0})
            lines = [f"共 {len(rows)} 个数据集："]
            for d in rows:
                cnt = len((await ctx.db.execute(
                    select(EvalQuestion.id).where(EvalQuestion.dataset_id == d.id)
                )).all())
                lines.append(f"  [{d.id}] {d.name}（{cnt} 题）{('｜KB ' + str(d.kb_ids)) if d.kb_ids else ''}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "create_dataset":
            if not args.get("name"):
                return ToolResult(content="create_dataset 需要 name", is_error=True)
            d = EvalDataset(tenant_id=ctx.tenant_id, name=str(args["name"])[:128],
                            description=args.get("description"), kb_ids=args.get("kb_ids"),
                            created_by=ctx.user_id)
            ctx.db.add(d)
            await ctx.db.flush()
            return ToolResult(content=f"已创建评测集 #{d.id}「{d.name}」", data={"dataset_id": d.id})

        did = args.get("dataset_id")
        if action == "add_question":
            if not did or not args.get("question"):
                return ToolResult(content="add_question 需要 dataset_id 与 question", is_error=True)
            d = await ctx.db.get(EvalDataset, int(did))
            if not d or d.tenant_id != ctx.tenant_id:
                return ToolResult(content="数据集不存在", is_error=True)
            q = EvalQuestion(tenant_id=ctx.tenant_id, dataset_id=d.id,
                             question=str(args["question"]), expected_answer=args.get("expected_answer"),
                             expected_doc_ids=args.get("expected_doc_ids"))
            ctx.db.add(q)
            await ctx.db.flush()
            return ToolResult(content=f"已向「{d.name}」添加题目 #{q.id}", data={"question_id": q.id})

        if action == "list_questions":
            if not did:
                return ToolResult(content="list_questions 需要 dataset_id", is_error=True)
            rows = (await ctx.db.execute(
                select(EvalQuestion).where(EvalQuestion.dataset_id == int(did))
                .order_by(EvalQuestion.sort, EvalQuestion.id)
            )).scalars().all()
            if not rows:
                return ToolResult(content="数据集暂无题目", data={"count": 0})
            lines = [f"共 {len(rows)} 题："]
            for q in rows:
                lines.append(f"  [{q.id}] {q.question}"
                             + ("（有标准答案）" if q.expected_answer else ""))
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "run":
            if not did:
                return ToolResult(content="run 需要 dataset_id", is_error=True)
            d = await ctx.db.get(EvalDataset, int(did))
            if not d or d.tenant_id != ctx.tenant_id:
                return ToolResult(content="数据集不存在", is_error=True)
            qn = len((await ctx.db.execute(
                select(EvalQuestion.id).where(EvalQuestion.dataset_id == d.id)
            )).all())
            if qn == 0:
                return ToolResult(content="数据集没有题目，先 add_question", is_error=True)
            run = EvalRun(tenant_id=ctx.tenant_id, dataset_id=d.id, status="pending", total=qn)
            ctx.db.add(run)
            await ctx.db.flush()
            # 后台执行（不阻塞对话）
            import asyncio

            from app.core.db import AsyncSessionLocal
            from app.services.eval_service import run_eval

            async def _bg(rid: int, tk: int):
                async with AsyncSessionLocal() as s:
                    try:
                        await run_eval(s, run_id=rid, top_k=int(args.get("top_k") or 5))
                        await s.commit()
                    except Exception:  # noqa: BLE001
                        pass

            asyncio.create_task(_bg(run.id, ctx.tenant_id))
            return ToolResult(content=f"已启动评测（运行 #{run.id}，{qn} 题），稍后用 get_run 查看结果",
                              data={"run_id": run.id})

        if action == "get_run":
            rid = args.get("run_id")
            if not rid:
                return ToolResult(content="get_run 需要 run_id", is_error=True)
            run = await ctx.db.get(EvalRun, int(rid))
            if not run or run.tenant_id != ctx.tenant_id:
                return ToolResult(content="运行不存在", is_error=True)
            results = (await ctx.db.execute(
                select(EvalResult).where(EvalResult.run_id == run.id).limit(200)
            )).scalars().all()
            sm = run.summary or {}
            lines = [f"运行 #{run.id} 状态={run.status} 进度={run.progress}/{run.total}",
                     f"汇总：{sm}"]
            for r in results[:10]:
                lines.append(f"  · {r.question[:40]}｜忠实度={r.faithfulness} 命中={r.hit_expected}")
            return ToolResult(content="\n".join(lines),
                              data={"status": run.status, "summary": sm, "count": len(results)})

        if action == "list_runs":
            if not did:
                return ToolResult(content="list_runs 需要 dataset_id", is_error=True)
            rows = (await ctx.db.execute(
                select(EvalRun).where(EvalRun.dataset_id == int(did), EvalRun.tenant_id == ctx.tenant_id)
                .order_by(EvalRun.id.desc()).limit(20)
            )).scalars().all()
            if not rows:
                return ToolResult(content="暂无运行记录", data={"count": 0})
            lines = [f"共 {len(rows)} 次运行："]
            for r in rows:
                lines.append(f"  [{r.id}] {r.status} {r.progress}/{r.total}｜{(r.summary or {})}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "delete_dataset":
            if not did:
                return ToolResult(content="delete_dataset 需要 dataset_id", is_error=True)
            d = await ctx.db.get(EvalDataset, int(did))
            if not d or d.tenant_id != ctx.tenant_id:
                return ToolResult(content="数据集不存在", is_error=True)
            for q in (await ctx.db.execute(
                select(EvalQuestion).where(EvalQuestion.dataset_id == d.id)
            )).scalars().all():
                await ctx.db.delete(q)
            await ctx.db.delete(d)
            await ctx.db.flush()
            return ToolResult(content=f"已删除评测集 #{d.id}")
        return ToolResult(content=f"不支持的操作：{action}", is_error=True)


# ==================== 会话管理 ====================
class ManageConversationTool(WriteToolMixin):
    name = "manage_conversation"
    description = (
        "管理「当前用户自己的」问答会话（会话列表页）。\n"
        "action=list 列出我的会话（可按 keyword 过滤标题）；"
        "rename 重命名（conversation_id + title）；delete 删除；"
        "export 导出为 Markdown 文本。\n"
        "**只能操作自己创建的会话**，越权会被拒绝。"
    )
    required_permission = "chat:use"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "rename", "delete", "export"]},
            "conversation_id": {"type": "integer"},
            "title": {"type": "string"},
            "keyword": {"type": "string", "description": "list 按标题过滤"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        return {"list": "列出我的会话", "rename": f"重命名会话 #{args.get('conversation_id')}",
                "delete": f"删除会话 #{args.get('conversation_id')}",
                "export": f"导出会话 #{args.get('conversation_id')}"}.get(
                    str(args.get("action")), "会话操作")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Conversation

        action = str(args.get("action") or "")
        if action == "list":
            q = select(Conversation).where(
                Conversation.tenant_id == ctx.tenant_id, Conversation.user_id == ctx.user_id
            )
            if args.get("keyword"):
                q = q.where(Conversation.title.contains(str(args["keyword"])))
            rows = (await ctx.db.execute(
                q.order_by(Conversation.id.desc()).limit(int(args.get("limit") or 20))
            )).scalars().all()
            if not rows:
                return ToolResult(content="（暂无会话）", data={"count": 0})
            lines = [f"共 {len(rows)} 个会话："]
            for c in rows:
                lines.append(f"  [{c.id}] {c.title or '(无标题)'}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        cid = args.get("conversation_id")
        if not cid:
            return ToolResult(content=f"{action} 需要 conversation_id", is_error=True)
        c = await ctx.db.get(Conversation, int(cid))
        if not c or c.tenant_id != ctx.tenant_id or c.user_id != ctx.user_id:
            return ToolResult(content="会话不存在或不属于你", is_error=True)

        if action == "rename":
            if not args.get("title"):
                return ToolResult(content="rename 需要 title", is_error=True)
            c.title = str(args["title"])[:256]
            await ctx.db.flush()
            return ToolResult(content=f"已重命名会话 #{c.id}")
        if action == "delete":
            await ctx.db.delete(c)
            await ctx.db.flush()
            return ToolResult(content=f"已删除会话 #{c.id}")
        if action == "export":
            from app.models import Message

            msgs = (await ctx.db.execute(
                select(Message).where(Message.conversation_id == c.id)
                .order_by(Message.id)
            )).scalars().all()
            parts = [f"# {c.title or '会话导出'}", ""]
            for m in msgs:
                role = {"user": "**用户**", "assistant": "**助手**"}.get(m.role, m.role)
                parts.append(f"{role}：\n\n{str(m.content or '')[:4000]}\n")
            return ToolResult(content="\n".join(parts)[:20000],
                              data={"count": len(msgs), "conversation_id": c.id})
        return ToolResult(content=f"不支持的操作：{action}", is_error=True)


# 用户级个人工具：高频、面向「自己的」待办与会话，常驻下发（不经 find_tools 两跳）。
# 只声明 chat:use，普通用户即可用；操作范围严格限定为本人数据。
PERSONAL_TOOLS = [
    ManageReminderTool(),
    ManageConversationTool(),
]

# 管理类补全工具：走 find_tools 按需路由（需对应权限码）。
COMPLEMENT_TOOLS = [
    ManageRecordTemplateTool(),
    ManageQuickReplyTool(),
    ManageChannelUserTool(),
    ManageNotificationTool(),
    ManageEvalTool(),
]
