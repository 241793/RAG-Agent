"""邮件管理测试：账号/消息模型、用户级隔离、收发、可选入库、AI 工具。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select


def _ev(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _setup():
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import KnowledgeBase, Tenant, User

    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "mail"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="M", slug="mail"); db.add(t); await db.flush()
        u1 = (await db.execute(select(User).where(User.username == "mail_a"))).scalar_one_or_none()
        if not u1:
            u1 = User(tenant_id=t.id, username="mail_a", password_hash="x"); db.add(u1); await db.flush()
        u2 = (await db.execute(select(User).where(User.username == "mail_b"))).scalar_one_or_none()
        if not u2:
            u2 = User(tenant_id=t.id, username="mail_b", password_hash="x"); db.add(u2); await db.flush()
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "mail_kb"))).scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name="mail_kb", visibility="public")
            db.add(kb); await db.flush()
        await db.commit()
        return {"tid": t.id, "u1": u1.id, "u2": u2.id, "kb_id": kb.id}


def test_mail_models_registered():
    from app.models import MailAccount, MailMessage

    for f in ("imap_host", "smtp_host", "uid_cursor", "auto_ingest"):
        assert f in MailAccount.__table__.columns, f"MailAccount 缺字段 {f}"
    for f in ("folder", "subject", "body_text", "seen", "attachments", "document_id"):
        assert f in MailMessage.__table__.columns, f"MailMessage 缺字段 {f}"


def test_mail_message_user_isolation():
    """用户级隔离：B 看不到 A 的邮件。"""
    async def _run():
        from app.api.v1.mail import list_messages
        from app.core.db import AsyncSessionLocal
        from app.models import MailAccount, MailMessage

        d = await _setup()

        class UA:
            id = d["u1"]; tenant_id = d["tid"]

        class UB:
            id = d["u2"]; tenant_id = d["tid"]

        async with AsyncSessionLocal() as db:
            acc = MailAccount(tenant_id=d["tid"], user_id=d["u1"], label="A", email_addr="a@x.com",
                              imap_host="h", imap_username="u")
            db.add(acc); await db.flush()
            db.add(MailMessage(tenant_id=d["tid"], user_id=d["u1"], account_id=acc.id, folder="INBOX",
                               subject="A 的邮件", from_addr="x@y.com"))
            await db.commit()
            aid = acc.id

        async with AsyncSessionLocal() as db:
            # B 想读 A 账号的邮件 → 归属校验失败
            try:
                await list_messages(account_id=aid, user=UB(), db=db)
                raise AssertionError("B 不应能读 A 的邮件列表")
            except Exception as e:
                assert "不存在" in str(e), str(e)
    _ev(_run())


def test_send_writes_sent_folder(monkeypatch):
    """发信成功 → 本地写 Sent。"""
    async def _run():
        from app.core.db import AsyncSessionLocal
        from app.models import MailAccount, MailMessage
        from app.services import mail_service

        d = await _setup()

        def _fake_send(**kw):
            return "<mid@test>"  # 同步函数（真实 send_mail_sync 也是同步，经 to_thread 调用）

        monkeypatch.setattr(mail_service, "send_mail_sync", _fake_send)

        async with AsyncSessionLocal() as db:
            acc = MailAccount(tenant_id=d["tid"], user_id=d["u1"], label="A", email_addr="a@x.com",
                              imap_host="h", imap_username="u", smtp_host="smtp", smtp_port=587)
            db.add(acc); await db.flush()
            r = await mail_service.send_from_account(db, acc, to=["b@y.com"], subject="Hi",
                                                     body_text="hello")
            await db.commit()
            assert r["ok"], r
        async with AsyncSessionLocal() as db:
            sent = (await db.execute(select(MailMessage).where(MailMessage.folder == "Sent"))).scalars().all()
            assert len(sent) == 1 and sent[0].subject == "Hi"
            assert sent[0].to_addrs == ["b@y.com"]
    _ev(_run())


def test_send_without_smtp_rejected():
    async def _run():
        from app.core.db import AsyncSessionLocal
        from app.models import MailAccount
        from app.services import mail_service

        d = await _setup()
        async with AsyncSessionLocal() as db:
            acc = MailAccount(tenant_id=d["tid"], user_id=d["u1"], label="A", email_addr="a@x.com",
                              imap_host="h", imap_username="u")  # 无 smtp_host
            db.add(acc); await db.flush()
            r = await mail_service.send_from_account(db, acc, to=["b@y.com"], subject="x", body_text="y")
            assert not r["ok"] and "SMTP" in r["message"]
    _ev(_run())


def test_persist_message_dedup():
    """同 account+folder+uid 的邮件只存一次。"""
    async def _run():
        from app.core.db import AsyncSessionLocal
        from app.models import MailAccount, MailMessage
        from app.services import mail_service

        d = await _setup()
        async with AsyncSessionLocal() as db:
            acc = MailAccount(tenant_id=d["tid"], user_id=d["u1"], label="A", email_addr="a@x.com",
                              imap_host="h", imap_username="u", folder="INBOX")
            db.add(acc); await db.flush()
            parsed = {"uid": "42", "message_id": "<m>", "subject": "S", "from_addr": "x@y.com",
                      "to_addrs": [], "body_text": "b", "attachments": []}
            mid1, c1 = await mail_service._persist_message(db, acc, dict(parsed))
            mid2, c2 = await mail_service._persist_message(db, acc, dict(parsed))
            await db.commit()
            assert c1 is True and c2 is False and mid1 == mid2
            n = (await db.execute(select(MailMessage).where(MailMessage.account_id == acc.id))).scalars().all()
            assert len(n) == 1
    _ev(_run())


def test_parse_one_message_extracts_fields():
    """解析原始邮件：主题解码 / 地址 / 正文。"""
    from app.services.mail_service import _parse_one_message

    raw = (
        b"From: Alice <alice@x.com>\r\nTo: bob@y.com, carol@z.com\r\n"
        b"Subject: Meeting\r\nDate: Mon, 15 Oct 2026 10:00:00 +0800\r\n"
        b"Message-ID: <abc@x.com>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHello body\r\n"
    )
    p = _parse_one_message(raw, "7")
    assert p["subject"] == "Meeting"
    assert p["from_addr"] == "alice@x.com" and p["from_name"] == "Alice"
    assert p["to_addrs"] == ["bob@y.com", "carol@z.com"]
    assert p["body_text"] == "Hello body"
    assert p["message_id"] == "<abc@x.com>"
    assert p["date"] and p["date"] > 0


def test_manage_mail_tool_registered_and_confirm():
    from app.agents.tools.registry import registry

    resident = {t.name for t in registry.all_builtin()}
    assert "manage_mail" in resident, "manage_mail 应常驻"
    t = registry.get_builtin("manage_mail")
    assert t.required_permission == "chat:use"
    # 发信/回复需确认；列表/标记免确认
    assert t.needs_confirm({"action": "send"}) is True
    assert t.needs_confirm({"action": "reply"}) is True
    assert t.needs_confirm({"action": "list_messages"}) is False
    assert t.needs_confirm({"action": "mark"}) is False


def test_manage_mail_user_isolation():
    """AI 工具：只能操作发起人自己的邮箱账号。"""
    async def _run():
        from app.agents.tools.base import ToolContext
        from app.agents.tools.mail_tools import ManageMailTool
        from app.core.db import AsyncSessionLocal
        from app.models import MailAccount
        from app.services.permission import PrincipalSet

        d = await _setup()
        async with AsyncSessionLocal() as db:
            acc = MailAccount(tenant_id=d["tid"], user_id=d["u1"], label="A", email_addr="a@x.com",
                              imap_host="h", imap_username="u")
            db.add(acc); await db.flush(); await db.commit()
            aid = acc.id

        # u2 用工具读 u1 的账号列表 → 看不到
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["u2"], tenant_id=d["tid"]),
                              tenant_id=d["tid"], user_id=d["u2"])
            r = await ManageMailTool().execute({"action": "list_accounts"}, ctx)
            assert "还没有配置" in r.content or "没有" in r.content
        # u2 试图列 u1 账号的邮件 → 账号不存在
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["u2"], tenant_id=d["tid"]),
                              tenant_id=d["tid"], user_id=d["u2"])
            r = await ManageMailTool().execute({"action": "list_messages", "account_id": aid}, ctx)
            assert r.is_error and "不存在" in r.content
    _ev(_run())


def test_email_source_uses_mail_account():
    """邮件入库源引用个人邮箱账号：_resolve_account 取回；跨用户引用被拒。"""
    async def _run():
        from app.api.v1.email_sources import _validate_source_account
        from app.core.db import AsyncSessionLocal
        from app.models import MailAccount

        d = await _setup()
        async with AsyncSessionLocal() as db:
            acc = MailAccount(tenant_id=d["tid"], user_id=d["u1"], label="A", email_addr="a@x.com",
                              imap_host="imap.a.com", imap_username="a@x.com")
            db.add(acc); await db.flush(); await db.commit()
            aid = acc.id

        class U1:
            id = d["u1"]; tenant_id = d["tid"]

        class U2:
            id = d["u2"]; tenant_id = d["tid"]

        # u1 引用自己的账号 → 通过
        async with AsyncSessionLocal() as db:
            await _validate_source_account(db, aid, U1())
        # u2 引用 u1 的账号 → 拒绝
        async with AsyncSessionLocal() as db:
            try:
                await _validate_source_account(db, aid, U2())
                raise AssertionError("u2 不应能引用 u1 的邮箱")
            except Exception as e:
                assert "不属于" in str(e) or "不存在" in str(e)
    _ev(_run())


def test_conn_params_resolves_from_account():
    """引用账号时，连接参数取自 MailAccount（字段名映射正确）。"""
    from app.services.email_ingest_service import _conn_params

    class Src:
        imap_host = ""; imap_port = 993; use_ssl = True
        username = ""; password = None; folder = "INBOX"

    class Acc:
        imap_host = "imap.personal.com"; imap_port = 993; imap_use_ssl = False
        imap_username = "me@personal.com"; imap_password = "enc:pw"; folder = "INBOX"

    cp = _conn_params(Src(), Acc())
    assert cp.imap_host == "imap.personal.com"
    assert cp.username == "me@personal.com"
    assert cp.use_ssl is False
    assert cp.password == "enc:pw"
    # 不引用账号 → 用 src 自带
    cp2 = _conn_params(Src(), None)
    assert cp2.imap_host == ""
