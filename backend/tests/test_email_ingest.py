"""邮件入库：密码加密、过滤逻辑、落库流程（mock IMAP）。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Document, EmailSource, KnowledgeBase, Tenant, User
from app.services import email_ingest_service as E


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "eml"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="EML", slug="eml"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "eml_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="eml_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == "eml_kb"))).scalar_one_or_none()
        if not kb:
            kb = KnowledgeBase(tenant_id=t.id, name="eml_kb", visibility="public", embedding_dim=64, owner_id=u.id)
            db.add(kb); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id, "kb_id": kb.id}


def test_matches_filter():
    class S:
        allow_from = "boss@corp.com"
        subject_keywords = "报告,报表"

    assert E._matches(S(), {"from": "Boss@corp.com <boss@corp.com>", "subject": "月度报告"}) is True
    assert E._matches(S(), {"from": "other@x.com", "subject": "报告"}) is False
    assert E._matches(S(), {"from": "boss@corp.com", "subject": "闲聊"}) is False
    class S2:
        allow_from = None
        subject_keywords = None
    assert E._matches(S2(), {"from": "any@x.com", "subject": "任意"}) is True


def test_decode_header():
    assert E._decode_header(None) == ""
    assert E._decode_header("plain subject") == "plain subject"
    # RFC2047 编码（Base64 UTF-8）
    assert E._decode_header("=?utf-8?B?5pWw5o2uLnhsc3g=?=") == "数据.xlsx"
    # RFC2047 编码（GB2312）
    assert E._decode_header("=?gb2312?B?yv2+3S54bHN4?=") == "数据.xlsx"
    # 非标准：UTF-8 直接塞进头部（latin-1 读成乱码）→ 应还原
    garbled = "数据.xlsx".encode("utf-8").decode("latin-1")
    assert E._decode_header(garbled) == "数据.xlsx"


def test_safe_decode_unknown_charset():
    # 非标准字符集名不应抛错
    assert E._safe_decode("正文".encode("utf-8"), "unknown-8bit") == "正文"
    assert E._safe_decode("正文".encode("utf-8"), "x-unknown") == "正文"
    assert E._safe_decode(b"abc", None) == "abc"
    # GBK 回退
    assert E._safe_decode("中文".encode("gbk"), "unknown-8bit") == "中文"


def test_ingest_one_text_and_attachment(monkeypatch):
    """正文 + 附件入库（mock storage + enqueue）。"""
    async def _run():
        d = await _setup()
        enqueued = []

        async def _fake_enqueue(doc_id):
            enqueued.append(doc_id)

        import app.tasks.ingest_tasks as it
        monkeypatch.setattr(it, "enqueue_document", _fake_enqueue)

        async with AsyncSessionLocal() as db:
            src = EmailSource(
                tenant_id=d["tenant_id"], name="s", imap_host="h", username="u",
                kb_id=d["kb_id"], ingest_mode="both", enabled=True,
            )
            db.add(src); await db.commit(); srcid = src.id
        async with AsyncSessionLocal() as db:
            src = await db.get(EmailSource, srcid)
            msg = {"uid": "1", "subject": "测试邮件", "from": "a@b.com",
                   "text": "邮件正文内容",
                   "attachments": [{"name": "报表.xlsx", "data": b"fake-xlsx-bytes"}]}
            n = await E._ingest_one(db, src, msg)
            await db.commit()
            assert n == 2  # 正文 + 附件
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(Document).where(Document.kb_id == d["kb_id"]))).scalars().all()
            assert len(rows) == 2
            assert any(r.source_type == "email" for r in rows)
    asyncio.new_event_loop().run_until_complete(_run())


def test_ingest_dedup(monkeypatch):
    """相同内容重复入库应去重。"""
    async def _run():
        d = await _setup()
        async def _fake_enqueue(doc_id):
            pass
        import app.tasks.ingest_tasks as it
        monkeypatch.setattr(it, "enqueue_document", _fake_enqueue)
        async with AsyncSessionLocal() as db:
            src = EmailSource(tenant_id=d["tenant_id"], name="s2", imap_host="h", username="u",
                              kb_id=d["kb_id"], ingest_mode="body", enabled=True)
            db.add(src); await db.commit(); srcid = src.id
        msg = {"uid": "9", "subject": "去重", "from": "a@b.com", "text": "完全相同的内容", "attachments": []}
        async with AsyncSessionLocal() as db:
            n1 = await E._ingest_one(db, await db.get(EmailSource, srcid), msg)
            await db.commit()
        async with AsyncSessionLocal() as db:
            n2 = await E._ingest_one(db, await db.get(EmailSource, srcid), msg)
            await db.commit()
        assert n1 == 1 and n2 == 0  # 第二次被去重
    asyncio.new_event_loop().run_until_complete(_run())


def test_sync_source_skips_disabled():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            src = EmailSource(tenant_id=d["tenant_id"], name="d", imap_host="h", username="u",
                              kb_id=d["kb_id"], enabled=False)
            db.add(src); await db.flush()
            r = await E.sync_source(db, src)
            assert r["ok"] is False and "禁用" in r["message"]
    asyncio.new_event_loop().run_until_complete(_run())


def test_email_source_endpoints_registered():
    from app.api.v1.email_sources import router

    paths = {r.path for r in router.routes}
    assert "/email-sources" in paths
    assert any("sync" in p for p in paths)
    assert any("test" in p for p in paths)


def test_password_encrypted():
    from app.core.crypto import decrypt, encrypt

    enc = encrypt("secret-pwd")
    assert enc.startswith("enc:") and decrypt(enc) == "secret-pwd"
