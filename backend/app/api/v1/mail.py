"""个人邮件管理接口：邮箱账号 CRUD + 收件箱 + 发信。

用户级：所有端点强制 `tenant_id + user_id` 过滤（只能操作自己的邮箱）。
权限沿用 `chat:use`（个人邮箱是个人工具，不引入新权限码）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import require_permission
from app.models import KnowledgeBase, MailAccount, MailMessage, User
from app.schemas.mail import (
    MailAccountIn,
    MailAccountOut,
    MailMessageDetail,
    MailMessageOut,
    MailSendIn,
)
from app.services.audit_service import audited

router = APIRouter(prefix="/mail", tags=["mail"])


def _acct_out(a: MailAccount) -> MailAccountOut:
    return MailAccountOut(
        id=a.id, label=a.label, email_addr=a.email_addr, from_name=a.from_name,
        imap_host=a.imap_host, imap_port=a.imap_port, imap_use_ssl=a.imap_use_ssl,
        imap_username=a.imap_username, imap_password_set=bool(a.imap_password),
        folder=a.folder, smtp_host=a.smtp_host, smtp_port=a.smtp_port,
        smtp_use_ssl=a.smtp_use_ssl, smtp_starttls=a.smtp_starttls,
        smtp_username=a.smtp_username, smtp_password_set=bool(a.smtp_password),
        auto_ingest=a.auto_ingest, default_kb_id=a.default_kb_id, allow_from=a.allow_from,
        subject_keywords=a.subject_keywords, auto_tags=a.auto_tags,
        last_poll_at=a.last_poll_at, ingested_count=a.ingested_count or 0,
        enabled=a.enabled, status=a.status, last_error=a.last_error,
    )


async def _get_account(db: AsyncSession, account_id: int, user: User) -> MailAccount:
    a = await db.get(MailAccount, account_id)
    if not a or a.tenant_id != user.tenant_id or a.user_id != user.id:
        raise NotFoundError("邮箱账号不存在")
    return a


# ==================== 账号 ====================
@router.get("/accounts", response_model=list[MailAccountOut])
async def list_accounts(
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> list[MailAccountOut]:
    rows = (await db.execute(
        select(MailAccount).where(
            MailAccount.tenant_id == user.tenant_id, MailAccount.user_id == user.id
        ).order_by(MailAccount.id.desc())
    )).scalars().all()
    return [_acct_out(a) for a in rows]


@router.post("/accounts", response_model=MailAccountOut)
@audited("mail.account_create", "mail_account")
async def create_account(
    body: MailAccountIn,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> MailAccountOut:
    if body.default_kb_id:
        kb = await db.get(KnowledgeBase, body.default_kb_id)
        if not kb or kb.tenant_id != user.tenant_id:
            raise NotFoundError("目标知识库不存在")
    a = MailAccount(
        tenant_id=user.tenant_id, user_id=user.id, label=body.label[:128],
        email_addr=body.email_addr, from_name=body.from_name,
        imap_host=body.imap_host, imap_port=body.imap_port, imap_use_ssl=body.imap_use_ssl,
        imap_username=body.imap_username,
        imap_password=encrypt(body.imap_password) if body.imap_password else None,
        folder=body.folder or "INBOX",
        smtp_host=body.smtp_host, smtp_port=body.smtp_port, smtp_use_ssl=body.smtp_use_ssl,
        smtp_starttls=body.smtp_starttls, smtp_username=body.smtp_username,
        smtp_password=encrypt(body.smtp_password) if body.smtp_password else None,
        auto_ingest=body.auto_ingest, default_kb_id=body.default_kb_id,
        allow_from=body.allow_from, subject_keywords=body.subject_keywords,
        auto_tags=body.auto_tags, tag_rules=body.tag_rules, enabled=body.enabled,
    )
    db.add(a)
    await db.flush()
    return _acct_out(a)


@router.put("/accounts/{account_id}", response_model=MailAccountOut)
@audited("mail.account_update", "mail_account", id_arg="account_id")
async def update_account(
    account_id: int,
    body: MailAccountIn,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> MailAccountOut:
    a = await _get_account(db, account_id, user)
    if body.default_kb_id:
        kb = await db.get(KnowledgeBase, body.default_kb_id)
        if not kb or kb.tenant_id != user.tenant_id:
            raise NotFoundError("目标知识库不存在")
    a.label = body.label[:128]; a.email_addr = body.email_addr; a.from_name = body.from_name
    a.imap_host = body.imap_host; a.imap_port = body.imap_port; a.imap_use_ssl = body.imap_use_ssl
    a.imap_username = body.imap_username; a.folder = body.folder or "INBOX"
    if body.imap_password:  # 留空=不变
        a.imap_password = encrypt(body.imap_password)
    a.smtp_host = body.smtp_host; a.smtp_port = body.smtp_port; a.smtp_use_ssl = body.smtp_use_ssl
    a.smtp_starttls = body.smtp_starttls; a.smtp_username = body.smtp_username
    if body.smtp_password:
        a.smtp_password = encrypt(body.smtp_password)
    a.auto_ingest = body.auto_ingest; a.default_kb_id = body.default_kb_id
    a.allow_from = body.allow_from; a.subject_keywords = body.subject_keywords
    a.auto_tags = body.auto_tags; a.tag_rules = body.tag_rules; a.enabled = body.enabled
    await db.flush()
    return _acct_out(a)


@router.delete("/accounts/{account_id}")
@audited("mail.account_delete", "mail_account", id_arg="account_id")
async def delete_account(
    account_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    a = await _get_account(db, account_id, user)
    # 连带删除该账号的邮件
    from sqlalchemy import delete as _del

    await db.execute(_del(MailMessage).where(MailMessage.account_id == a.id))
    await db.delete(a)
    await db.flush()
    return {"message": "已删除"}


@router.post("/accounts/{account_id}/test")
async def test_account(
    account_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.mail_service import test_account as _test

    a = await _get_account(db, account_id, user)
    return await _test(a)


@router.post("/accounts/{account_id}/sync")
async def sync_account(
    account_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.mail_service import poll_account

    a = await _get_account(db, account_id, user)
    r = await poll_account(db, a)
    await db.commit()
    return r


# ==================== 邮件 ====================
@router.get("/messages", response_model=list[MailMessageOut])
async def list_messages(
    account_id: int,
    folder: str = "INBOX",
    q: str | None = None,
    unread: bool = False,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> list[MailMessageOut]:
    await _get_account(db, account_id, user)  # 归属校验
    stmt = select(MailMessage).where(
        MailMessage.tenant_id == user.tenant_id, MailMessage.user_id == user.id,
        MailMessage.account_id == account_id, MailMessage.folder == folder,
    )
    if unread:
        stmt = stmt.where(MailMessage.seen.is_(False))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((MailMessage.subject.ilike(like)) | (MailMessage.from_addr.ilike(like)))
    rows = (await db.execute(
        stmt.order_by(MailMessage.date.desc().nulls_last(), MailMessage.id.desc()).limit(limit)
    )).scalars().all()
    return [MailMessageOut.model_validate(m) for m in rows]


@router.get("/messages/{msg_id}", response_model=MailMessageDetail)
async def read_message(
    msg_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> MailMessageDetail:
    m = await db.get(MailMessage, msg_id)
    if not m or m.tenant_id != user.tenant_id or m.user_id != user.id:
        raise NotFoundError("邮件不存在")
    return MailMessageDetail.model_validate(m)


@router.post("/messages/{msg_id}/{action}")
async def message_action(
    msg_id: int,
    action: str,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """action: read | unread | star | unstar | delete。"""
    m = await db.get(MailMessage, msg_id)
    if not m or m.tenant_id != user.tenant_id or m.user_id != user.id:
        raise NotFoundError("邮件不存在")
    if action == "read":
        m.seen = True
    elif action == "unread":
        m.seen = False
    elif action == "star":
        m.starred = True
    elif action == "unstar":
        m.starred = False
    elif action == "delete":
        m.folder = "Trash"
    else:
        raise NotFoundError(f"未知操作：{action}")
    await db.flush()
    return {"ok": True, "message": "已更新"}


@router.post("/send")
@audited("mail.send", "mail_message")
async def send_mail(
    body: MailSendIn,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.mail_service import send_from_account

    a = await _get_account(db, body.account_id, user)
    in_reply_to = None
    if body.reply_to_id:
        orig = await db.get(MailMessage, body.reply_to_id)
        if orig and orig.user_id == user.id:
            in_reply_to = orig.message_id
    r = await send_from_account(db, a, to=body.to, cc=body.cc, subject=body.subject,
                                body_text=body.body_text, body_html=body.body_html,
                                in_reply_to=in_reply_to)
    await db.commit()
    return r
