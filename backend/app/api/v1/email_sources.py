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
        id=s.id, name=s.name, imap_host=s.imap_host, imap_port=s.imap_port, use_ssl=s.use_ssl,
        username=s.username, password_set=bool(s.password), folder=s.folder, kb_id=s.kb_id,
        ingest_mode=s.ingest_mode, allow_from=s.allow_from, subject_keywords=s.subject_keywords,
        enabled=s.enabled, status=s.status, last_error=s.last_error,
        last_sync_at=s.last_sync_at, ingested_count=s.ingested_count or 0,
    )


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
    s = EmailSource(
        tenant_id=user.tenant_id, name=body.name, imap_host=body.imap_host,
        imap_port=body.imap_port, use_ssl=body.use_ssl, username=body.username,
        password=encrypt(body.password) if body.password else None,
        folder=body.folder, kb_id=body.kb_id, ingest_mode=body.ingest_mode,
        allow_from=body.allow_from, subject_keywords=body.subject_keywords,
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
    from app.services.email_ingest_service import test_source as _test

    s = await db.get(EmailSource, source_id)
    if not s or s.tenant_id != user.tenant_id:
        raise NotFoundError("邮件源不存在")
    return await _test(s)


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
