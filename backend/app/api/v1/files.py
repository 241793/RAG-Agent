"""文件管理接口：产物/上传文件的列表、下载、删除、清理。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, PermissionDeniedError
from app.ingest.storage import get_storage
from app.middleware.auth_dep import FileAccess, get_file_access, require_permission, user_has_permission
from app.models import Artifact, User
from app.services.audit_service import audited

router = APIRouter(prefix="/files", tags=["files"])

_SORT_FIELDS = {"created_at", "size", "file_name"}


def _to_out(a: Artifact, uname: str | None = None) -> dict:
    return {
        "id": a.id, "file_name": a.file_name, "file_ext": a.file_ext, "mime": a.mime,
        "size": a.size, "source": a.source, "user_id": a.user_id, "user_name": uname,
        "conversation_id": a.conversation_id, "created_at": a.created_at,
        "expires_at": a.expires_at,
    }


@router.get("")
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source: str | None = None,
    user_id: int | None = None,
    q: str | None = None,
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    user: User = Depends(require_permission("file:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cond = [Artifact.tenant_id == user.tenant_id]
    if source:
        cond.append(Artifact.source == source)
    if user_id:
        cond.append(Artifact.user_id == user_id)
    if q:
        cond.append(Artifact.file_name.ilike(f"%{q}%"))
    total = (await db.execute(select(func.count()).select_from(select(Artifact).where(*cond).subquery()))).scalar_one()
    # 白名单排序，防注入
    field = sort if sort in _SORT_FIELDS else "created_at"
    col = getattr(Artifact, field)
    order_clause = col.asc() if order == "asc" else col.desc()
    rows = (
        await db.execute(
            select(Artifact).where(*cond).order_by(order_clause)
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    ids = {r.user_id for r in rows}
    names: dict[int, str] = {}
    if ids:
        for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all():
            names[u.id] = u.display_name or u.username
    return {"total": total, "items": [_to_out(r, names.get(r.user_id)) for r in rows]}


@router.get("/{artifact_id}/download")
async def download_file(
    artifact_id: int,
    inline: int = 0,
    access: FileAccess = Depends(get_file_access),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """下载/预览文件：登录态（本人 / file:manage / chat:read_all）或签名 token。"""
    if access.via == "token":
        if access.scope != "artifact" or access.artifact_id != artifact_id:
            raise PermissionDeniedError("链接无权访问该文件")
        art = await db.get(Artifact, artifact_id)
        if not art or art.tenant_id != access.tenant_id:
            raise NotFoundError("文件不存在")
    else:
        user = access.user
        art = await db.get(Artifact, artifact_id)
        if not art or art.tenant_id != user.tenant_id:
            raise NotFoundError("文件不存在")
        allowed = (
            art.user_id == user.id
            or await user_has_permission(db, user, "file:manage")
            or await user_has_permission(db, user, "chat:read_all")
        )
        if not allowed:
            raise NotFoundError("文件不存在")
    try:
        p = get_storage().path(art.file_key, tenant_id=art.tenant_id)
    except ValueError:
        raise NotFoundError("文件不存在")
    if not p.is_file():
        raise NotFoundError("文件已丢失")
    from app.core.http_utils import content_disposition

    return FileResponse(str(p), headers={
        "Content-Disposition": content_disposition(art.file_name, inline=bool(inline)),
    })


@router.get("/{artifact_id}/url")
async def sign_artifact_url(
    artifact_id: int,
    user: User = Depends(require_permission("chat:use")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """为产物签发短期预览 URL（inline）。"""
    from app.core.config import settings
    from app.core.security import create_file_token

    art = await db.get(Artifact, artifact_id)
    if not art or art.tenant_id != user.tenant_id:
        raise NotFoundError("文件不存在")
    token = create_file_token(scope="artifact", tenant_id=user.tenant_id, artifact_id=artifact_id)
    return {
        "url": f"/api/v1/files/{artifact_id}/download?inline=1&t={token}",
        "download_url": f"/api/v1/files/{artifact_id}/download?t={token}",
        "expires_in": settings.file_token_expire_minutes * 60,
    }


@router.delete("/{artifact_id}")
@audited("file.delete", "artifact", id_arg="artifact_id")
async def delete_file(
    artifact_id: int,
    user: User = Depends(require_permission("file:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    art = await db.get(Artifact, artifact_id)
    if not art or art.tenant_id != user.tenant_id:
        raise NotFoundError("文件不存在")
    try:
        get_storage().delete(art.file_key)
    except Exception:  # noqa: BLE001
        pass
    await db.delete(art)
    await db.flush()
    return {"message": "已删除"}


@router.post("/cleanup")
async def cleanup_files(
    user: User = Depends(require_permission("file:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动清理过期产物。"""
    from app.tasks.artifact_tasks import cleanup_expired_artifacts

    n = await cleanup_expired_artifacts(db)
    return {"message": f"已清理 {n} 个过期文件"}
