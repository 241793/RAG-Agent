"""知识库完善测试：渠道附件入库策略、邮件 UID 游标增量、邮件自动标签。"""
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
        t = (await db.execute(select(Tenant).where(Tenant.slug == "kbi"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="KBI", slug="kbi"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "kbi_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="kbi_u", password_hash="x", is_admin=True)
            db.add(u); await db.flush()
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "kbi_kb"))).scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name="kbi_kb", visibility="public")
            db.add(kb); await db.flush()
        await db.commit()
        return {"tid": t.id, "uid": u.id, "kb_id": kb.id}


# ---------- 渠道附件入库 ----------
class _FakeChannel:
    def __init__(self, **kw):
        self.attach_ingest = "off"
        self.attach_kb_ids = None
        self.default_kb_ids = None
        self.attach_max_mb = 20
        self.attach_types = None
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeCU:
    def __init__(self, bound=None):
        self.bound_user_id = bound


def test_channel_attach_ingest_off():
    """off 模式：不入库。"""
    async def _run():
        from app.channels.dispatcher import _maybe_ingest_attachment
        from app.core.db import AsyncSessionLocal
        from app.services.permission import PrincipalSet

        d = await _setup()
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tid"])
            ch = _FakeChannel(attach_ingest="off", default_kb_ids=[d["kb_id"]])
            r = await _maybe_ingest_attachment(db, ps=ps, channel=ch, cu=_FakeCU(),
                                               name="a.pdf", data=b"x", ext="pdf",
                                               mime="application/pdf", file_key="k")
            assert r is None
    _ev(_run())


def test_channel_attach_ingest_bound_requires_bound_user():
    """bound 模式：未绑定用户被拒；已绑定放行。"""
    async def _run():
        from app.channels.dispatcher import _maybe_ingest_attachment
        from app.core.db import AsyncSessionLocal
        from app.services.permission import PrincipalSet

        d = await _setup()
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tid"])
            ch = _FakeChannel(attach_ingest="bound", default_kb_ids=[d["kb_id"]])
            # 未绑定 → None
            r1 = await _maybe_ingest_attachment(db, ps=ps, channel=ch, cu=_FakeCU(bound=None),
                                                name="a.pdf", data=b"bound-test", ext="pdf",
                                                mime="application/pdf", file_key="k1")
            assert r1 is None
            # 已绑定 → 建文档
            r2 = await _maybe_ingest_attachment(db, ps=ps, channel=ch, cu=_FakeCU(bound=d["uid"]),
                                                name="b.pdf", data=b"bound-test2", ext="pdf",
                                                mime="application/pdf", file_key="k2")
            assert r2 is not None
    _ev(_run())


def test_channel_attach_ingest_size_and_type_gate():
    """资源闸：超大小 / 非白名单类型被拒。"""
    async def _run():
        from app.channels.dispatcher import _maybe_ingest_attachment
        from app.core.db import AsyncSessionLocal
        from app.services.permission import PrincipalSet

        d = await _setup()
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tid"])
            # 超大小（1MB 限制，给 2MB）
            ch1 = _FakeChannel(attach_ingest="all", default_kb_ids=[d["kb_id"]], attach_max_mb=1)
            r1 = await _maybe_ingest_attachment(db, ps=ps, channel=ch1, cu=_FakeCU(),
                                                name="big.pdf", data=b"x" * (2 * 1024 * 1024),
                                                ext="pdf", mime="application/pdf", file_key="kb")
            assert r1 is None
            # 非白名单类型（.exe）
            ch2 = _FakeChannel(attach_ingest="all", default_kb_ids=[d["kb_id"]], attach_types="pdf,docx")
            r2 = await _maybe_ingest_attachment(db, ps=ps, channel=ch2, cu=_FakeCU(),
                                                name="bad.exe", data=b"x", ext="exe",
                                                mime="application/octet-stream", file_key="ke")
            assert r2 is None
    _ev(_run())


def test_channel_attach_ingest_dedup():
    """幂等闸：同内容二次上传不重复建文档。"""
    async def _run():
        from app.channels.dispatcher import _maybe_ingest_attachment
        from app.core.db import AsyncSessionLocal
        from app.services.permission import PrincipalSet

        d = await _setup()
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tid"])
            ch = _FakeChannel(attach_ingest="all", default_kb_ids=[d["kb_id"]])
            payload = b"dedup-unique-content-zzz"
            r1 = await _maybe_ingest_attachment(db, ps=ps, channel=ch, cu=_FakeCU(),
                                                name="d.txt", data=payload, ext="txt",
                                                mime="text/plain", file_key="kd1")
            r2 = await _maybe_ingest_attachment(db, ps=ps, channel=ch, cu=_FakeCU(),
                                                name="d.txt", data=payload, ext="txt",
                                                mime="text/plain", file_key="kd2")
            assert r1 is not None and r2 is None, "同内容第二次应去重"
    _ev(_run())


# ---------- 邮件 UID 游标 ----------
def test_email_uid_cursor_uses_cursor_search():
    """UID 游标：cursor>0 时按 UID cursor+1:* 搜索（而非 ALL）。"""
    async def _run():
        from app.services.email_ingest_service import _fetch_messages
        import imaplib

        class FakeConn:
            def __init__(self): self.searched = None
            def login(self, u, p): return ("OK", [])
            def select(self, f, readonly=True):
                return ("OK", [b"1234 (UIDVALIDITY 999)"])
            def uid(self, cmd, *args):
                if cmd == "search":
                    self.searched = args[-1] if args else None
                    return ("OK", [])
                return ("OK", [])
            def close(self): pass
            def logout(self): pass

        fake = FakeConn()
        orig = imaplib.IMAP4_SSL
        imaplib.IMAP4_SSL = lambda *a, **k: fake
        try:
            class S:
                use_ssl = True; imap_host = "h"; imap_port = 993; username = "u"
                password = None; folder = "INBOX"; uid_cursor = 10; uid_validity = 999
                seen_uids = []
            _msgs, _max_uid, validity = _fetch_messages(S())
            assert fake.searched == "UID 11:*", fake.searched
            assert validity == 999
        finally:
            imaplib.IMAP4_SSL = orig
    _ev(_run())


def test_email_uidvalidity_change_resets_cursor():
    """UIDVALIDITY 变化 → 邮箱重建 → 游标归零（走 ALL）。"""
    async def _run():
        from app.services.email_ingest_service import _fetch_messages
        import imaplib

        class FakeConn:
            def __init__(self): self.searched = None
            def login(self, u, p): return ("OK", [])
            def select(self, f, readonly=True):
                return ("OK", [b"1234 (UIDVALIDITY 888)"])
            def uid(self, cmd, *args):
                if cmd == "search":
                    self.searched = args[-1] if args else None
                    return ("OK", [])
                return ("OK", [])
            def close(self): pass
            def logout(self): pass

        fake = FakeConn()
        orig = imaplib.IMAP4_SSL
        imaplib.IMAP4_SSL = lambda *a, **k: fake
        try:
            class S:
                use_ssl = True; imap_host = "h"; imap_port = 993; username = "u"
                password = None; folder = "INBOX"; uid_cursor = 10; uid_validity = 999  # 与 888 不同
                seen_uids = []
            _fetch_messages(S())
            assert fake.searched == "ALL", "UIDVALIDITY 变化应重置游标走 ALL"
        finally:
            imaplib.IMAP4_SSL = orig
    _ev(_run())


# ---------- 邮件自动标签 ----------
def test_email_auto_tags_resolution():
    from app.services.email_ingest_service import _resolve_tags

    class S:
        auto_tags = ["邮件", "归档"]
        tag_rules = {"发票": ["财务"], "合同": ["法务", "重要"]}

    assert _resolve_tags(S(), "本月发票", "请查收") == ["邮件", "归档", "财务"]
    assert _resolve_tags(S(), "合同评审", "") == ["邮件", "归档", "法务", "重要"]
    assert _resolve_tags(S(), "普通主题", "普通正文") == ["邮件", "归档"]

    class S2:
        auto_tags = ["x", "x", "y"]
        tag_rules = None
    assert _resolve_tags(S2(), "", "") == ["x", "y"]


def test_email_source_schema_has_new_fields():
    from app.schemas.email_source import EmailSourceCreate, EmailSourceOut

    s = EmailSourceCreate(name="n", imap_host="h", username="u", kb_id=1,
                          auto_tags=["a"], tag_rules={"k": ["v"]})
    assert s.auto_tags == ["a"] and s.tag_rules == {"k": ["v"]}
    assert "uid_cursor" in EmailSourceOut.model_fields


def test_channel_model_has_attach_fields():
    from app.models.channel import Channel

    for f in ("attach_ingest", "attach_kb_ids", "attach_max_mb", "attach_types"):
        assert f in Channel.__table__.columns, f"缺字段 {f}"
