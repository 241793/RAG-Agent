"""邮件入库源接口：配置 IMAP 邮箱，定时拉取邮件（含附件）入库到知识库。

密码加密存储、读取脱敏。权限：复用 kb:update（配置入库源属于知识库管理动作）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import EmailSource, KnowledgeBase, User
from app.schemas.email_source import EmailSourceCreate, EmailSourceOut, EmailSourceUpdate
from app.services.audit_service import audited

router = APIRouter(prefix="/email-sources", tags=["email_source"])


def _to_out(s: EmailSource) -> EmailSourceOut:
    return EmailSourceOut(
        id=s.id, name=s.name, source_account_id=getattr(s, "source_account_id", None),
        imap_host=s.imap_host, imap_port=s.imap_port, use_ssl=s.use_ssl,
        username=s.username, password_set=bool(s.password), folder=s.folder, kb_id=s.kb_id,
        ingest_mode=s.ingest_mode, allow_from=s.allow_from, subject_keywords=s.subject_keywords,
        auto_tags=s.auto_tags, tag_rules=s.tag_rules, uid_cursor=s.uid_cursor or 0,
        enabled=s.enabled, status=s.status, last_error=s.last_error,
        last_sync_at=s.last_sync_at, ingested_count=s.ingested_count or 0,
    )


@router.get("/my-accounts")
async def my_mail_accounts(
    user: User = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """列出**当前用户自己的**个人邮箱账号，供「邮件入库」页选择复用（仅本人，防越权）。"""
    from app.models import MailAccount

    rows = (await db.execute(
        select(MailAccount).where(
            MailAccount.tenant_id == user.tenant_id, MailAccount.user_id == user.id
        ).order_by(MailAccount.id.desc())
    )).scalars().all()
    return [{"id": a.id, "label": a.label or a.email_addr, "email_addr": a.email_addr,
             "folder": a.folder} for a in rows]


async def _validate_source_account(db, source_account_id: int | None, user: User) -> None:
    """校验引用的个人邮箱账号属于当前用户（防借用他人邮箱）。"""
    if not source_account_id:
        return
    from app.models import MailAccount

    acc = await db.get(MailAccount, source_account_id)
    if not acc or acc.tenant_id != user.tenant_id or acc.user_id != user.id:
        raise NotFoundError("邮箱账号不存在或不属于你")


@router.get("", response_model=list[EmailSourceOut])
async def list_sources(
    user: User = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_db),
) -> list[EmailSourceOut]:
    rows = (await db.execute(
        select(EmailSource).where(EmailSource.tenant_id == user.tenant_id).order_by(EmailSource.id.desc())
    )).scalars().all()
    return [_to_out(s) for s in rows]


@router.post("", response_model=EmailSourceOut)
@audited("email_source.create", "email_source")
async def create_source(
    body: EmailSourceCreate,
    user: User = Depends(require_permission("kb:update")),
    db: AsyncSession = Depends(get_db),
) -> EmailSourceOut:
    kb = await db.get(KnowledgeBase, body.kb_id)
    if not kb or kb.tenant_id != user.tenant_id:
        raise NotFoundError("目标知识库不存在")
    if body.ingest_mode not in ("both", "attach", "body"):
        raise ValidationError("ingest_mode 只能为 both/attach/body")
    await _validate_source_account(db, body.source_account_id, user)
    # 引用个人邮箱账号时，IMAP 字段可留空（从账号取）
    if not body.source_account_id and not (body.imap_host and body.username):
        raise ValidationError("请选择邮箱账号，或填写 IMAP 主机与账号")
    use_self_imap = body.source_account_id is None
    s = EmailSource(
        tenant_id=user.tenant_id, name=body.name,
        source_account_id=body.source_account_id,
        imap_host=body.imap_host or "", imap_port=body.imap_port, use_ssl=body.use_ssl,
        username=body.username or "",
        password=(encrypt(body.password) if (body.password and use_self_imap) else None),
        folder=body.folder, kb_id=body.kb_id, ingest_mode=body.ingest_mode,
        allow_from=body.allow_from, subject_keywords=body.subject_keywords,
        auto_tags=body.auto_tags, tag_rules=body.tag_rules,
        enabled=body.enabled, uploaded_by=user.id, status="active",
    )
    db.add(s)
    await db.flush()
    return _to_out(s)


@router.patch("/{source_id}", response_model=EmailSourceOut)
@audited("email_source.update", "email_source", id_arg="source_id")
async def update_source(
    source_id: int,
    body: EmailSourceUpdate,
    user: User = Depends(require_permission("kb:update")),
    db: AsyncSession = Depends(get_db),
) -> EmailSourceOut:
    s = await db.get(EmailSource, source_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("邮件源不存在")
    data = body.model_dump(exclude_unset=True)
    if "source_account_id" in data:
        await _validate_source_account(db, data["source_account_id"], user)
    for k, v in data.items():
        if k == "password":
            s.password = encrypt(v) if v else None
        else:
            setattr(s, k, v)
    await db.flush()
    return _to_out(s)


@router.delete("/{source_id}")
@audited("email_source.delete", "email_source", id_arg="source_id")
async def delete_source(
    source_id: int,
    user: User = Depends(require_permission("kb:update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    s = await db.get(EmailSource, source_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("邮件源不存在")
    await db.delete(s)
    await db.flush()
    return {"message": "已删除"}


@router.post("/{source_id}/test")
async def test_source(
    source_id: int,
    user: User = Depends(require_permission("kb:update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """测试 IMAP 连接（登录 + 打开文件夹）。"""
    from app.services.email_ingest_service import _resolve_account
    from app.services.email_ingest_service import test_source as _test

    s = await db.get(EmailSource, source_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("邮件源不存在")
    account = await _resolve_account(db, s)
    return await _test(s, account=account)


@router.post("/{source_id}/sync")
async def sync_source(
    source_id: int,
    user: User = Depends(require_permission("kb:update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """立即拉取一次。"""
    from app.services.email_ingest_service import sync_source as _sync

    s = await db.get(EmailSource, source_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("邮件源不存在")
    r = await _sync(db, s)
    await db.commit()
    return r
