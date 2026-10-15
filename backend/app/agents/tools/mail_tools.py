"""AI 邮件工具：让 AI 管理当前用户的个人邮箱（读收件箱 / 写信 / 回复 / 标记）。

用户级：所有操作强制 `tenant_id + user_id`（AI 只能碰发起人自己的邮箱）。
写操作（发送/回复）走 HITL 确认；轻量标记操作可自动执行。
"""
from __future__ import annotations

from sqlalchemy import select

from app.agents.tools.base import ToolContext, ToolResult
from app.agents.tools.base import WriteToolMixin


def _addr_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
    return []


class ManageMailTool(WriteToolMixin):
    name = "manage_mail"
    description = (
        "管理**当前用户自己的**个人邮箱（收发）。\n"
        "action=list_accounts（列出邮箱账号，拿 account_id）；"
        "list_messages（列收件箱，参数 account_id/folder(默认 INBOX，可 Sent)/q 关键词/unread 只看未读）；"
        "read_message（读一封邮件全文，参数 message_id）；"
        "mark（标记，参数 message_id + mark=read/unread/star/unstar/delete）；"
        "send（发信，参数 account_id + to + subject + body_text，可选 cc）；"
        "reply（回复，参数 account_id + message_id + body_text）。\n"
        "只能操作当前用户自己的邮箱；发信会先弹确认。"
    )
    required_permission = "chat:use"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list_accounts", "list_messages", "read_message",
                                "mark", "send", "reply"]},
            "account_id": {"type": "integer"},
            "message_id": {"type": "integer", "description": "read_message/reply/mark 需要"},
            "folder": {"type": "string", "description": "列表文件夹：INBOX/Sent（默认 INBOX）"},
            "q": {"type": "string", "description": "按主题/发件人搜索"},
            "unread": {"type": "boolean", "description": "只看未读"},
            "mark": {"type": "string", "enum": ["read", "unread", "star", "unstar", "delete"]},
            "to": {"type": "array", "items": {"type": "string"}, "description": "收件人列表"},
            "cc": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "body_text": {"type": "string", "description": "正文"},
        },
        "required": ["action"],
    }

    def summarize(self, args: dict) -> str:
        a = args.get("action")
        if a == "send":
            return f"发送邮件给 {', '.join(_addr_list(args.get('to')))}（主题：{args.get('subject') or '(无)'}）"
        if a == "reply":
            return f"回复邮件 #{args.get('message_id')}"
        if a == "mark":
            return f"标记邮件 #{args.get('message_id')} 为 {args.get('mark')}"
        return {"list_accounts": "列出邮箱账号", "list_messages": "查看收件箱",
                "read_message": f"阅读邮件 #{args.get('message_id')}"}.get(a, "邮件操作")

    def needs_confirm(self, args: dict) -> bool:
        """发信/回复不可逆外发 → 必须确认；其余（读/标记）免确认。"""
        return str(args.get("action") or "") in ("send", "reply")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import MailAccount, MailMessage

        action = str(args.get("action") or "")

        async def _acc(aid: int) -> MailAccount | None:
            a = await ctx.db.get(MailAccount, aid)
            if not a or a.tenant_id != ctx.tenant_id or a.user_id != ctx.user_id:
                return None
            return a

        if action == "list_accounts":
            rows = (await ctx.db.execute(
                select(MailAccount).where(
                    MailAccount.tenant_id == ctx.tenant_id, MailAccount.user_id == ctx.user_id
                ).order_by(MailAccount.id.desc())
            )).scalars().all()
            if not rows:
                return ToolResult(content="你还没有配置邮箱账号，请在「邮件」页添加。")
            lines = [f"#{a.id} {a.label or a.email_addr} [{a.email_addr}]"
                     + ("（可发信）" if a.smtp_host else "（未配 SMTP，只能收）") for a in rows]
            return ToolResult(content="你的邮箱账号：\n" + "\n".join(lines))

        if action == "list_messages":
            aid = int(args.get("account_id") or 0)
            if not aid:
                return ToolResult(content="请提供 account_id（先用 list_accounts 查）", is_error=True)
            a = await _acc(aid)
            if not a:
                return ToolResult(content="邮箱账号不存在或无权访问", is_error=True)
            folder = str(args.get("folder") or "INBOX")
            stmt = select(MailMessage).where(
                MailMessage.tenant_id == ctx.tenant_id, MailMessage.user_id == ctx.user_id,
                MailMessage.account_id == aid, MailMessage.folder == folder,
            )
            if args.get("unread"):
                stmt = stmt.where(MailMessage.seen.is_(False))
            if args.get("q"):
                like = f"%{args['q']}%"
                stmt = stmt.where((MailMessage.subject.ilike(like)) | (MailMessage.from_addr.ilike(like)))
            rows = (await ctx.db.execute(
                stmt.order_by(MailMessage.date.desc().nulls_last(), MailMessage.id.desc()).limit(30)
            )).scalars().all()
            if not rows:
                return ToolResult(content=f"（{folder} 无邮件）", data={"count": 0})
            lines = [f"{folder} 共 {len(rows)} 封（最近）："]
            for m in rows:
                flag = "●" if not m.seen else "○"
                lines.append(f"  [{m.id}] {flag} {m.subject}｜{m.from_addr}")
            return ToolResult(content="\n".join(lines), data={"count": len(rows)})

        if action == "read_message":
            mid = int(args.get("message_id") or 0)
            m = await ctx.db.get(MailMessage, mid)
            if not m or m.tenant_id != ctx.tenant_id or m.user_id != ctx.user_id:
                return ToolResult(content="邮件不存在", is_error=True)
            body = m.body_text or (m.body_html or "")[:3000] or "(无正文)"
            return ToolResult(content=f"主题：{m.subject}\n发件人：{m.from_name or ''} <{m.from_addr}>\n"
                                     f"收件人：{', '.join(_addr_list(m.to_addrs))}\n\n{body[:5000]}",
                              data={"id": m.id, "subject": m.subject})

        if action == "mark":
            mid = int(args.get("message_id") or 0)
            m = await ctx.db.get(MailMessage, mid)
            if not m or m.tenant_id != ctx.tenant_id or m.user_id != ctx.user_id:
                return ToolResult(content="邮件不存在", is_error=True)
            mk = str(args.get("mark") or "")
            if mk == "read":
                m.seen = True
            elif mk == "unread":
                m.seen = False
            elif mk == "star":
                m.starred = True
            elif mk == "unstar":
                m.starred = False
            elif mk == "delete":
                m.folder = "Trash"
            else:
                return ToolResult(content=f"未知标记：{mk}", is_error=True)
            await ctx.db.flush()
            return ToolResult(content=f"已{mk}邮件 #{m.id}")

        if action in ("send", "reply"):
            from app.services.mail_service import send_from_account

            aid = int(args.get("account_id") or 0)
            a = await _acc(aid) if aid else None
            if not a:
                return ToolResult(content="邮箱账号不存在或无权访问", is_error=True)
            if not a.smtp_host:
                return ToolResult(content="该账号未配置 SMTP，无法发信", is_error=True)
            in_reply_to = None
            if action == "reply":
                mid = int(args.get("message_id") or 0)
                orig = await ctx.db.get(MailMessage, mid)
                if not orig or orig.user_id != ctx.user_id:
                    return ToolResult(content="待回复的邮件不存在", is_error=True)
                in_reply_to = orig.message_id
                to = _addr_list(orig.from_addr)
                subject = orig.subject if str(orig.subject).lower().startswith("re:") else f"Re: {orig.subject}"
            else:
                to = _addr_list(args.get("to"))
                subject = str(args.get("subject") or "")
            if not to:
                return ToolResult(content="缺少收件人", is_error=True)
            r = await send_from_account(ctx.db, a, to=to, cc=_addr_list(args.get("cc")),
                                        subject=subject, body_text=str(args.get("body_text") or ""),
                                        in_reply_to=in_reply_to)
            await ctx.db.flush()
            return ToolResult(content=r.get("message") or "已发送",
                              is_error=not r.get("ok"), data={"message_id": r.get("message_id")})

        return ToolResult(content=f"不支持的 action：{action}", is_error=True)
