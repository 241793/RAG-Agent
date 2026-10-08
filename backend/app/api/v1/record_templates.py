"""智能录单接口：录单模板 CRUD + 从文本抽取 + 记录管理 + 导出台账。

权限码 record:read / record:manage。
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.middleware.auth_dep import require_permission
from app.models import RecordEntry, RecordTemplate, User
from app.schemas.record_template import (
    EntryUpdate,
    ExtractIn,
    TemplateCreate,
    TemplateOut,
    TemplateUpdate,
)
from app.services.audit_service import audited

router = APIRouter(prefix="/record-templates", tags=["record"])


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    user: User = Depends(require_permission("record:read")),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateOut]:
    rows = (await db.execute(
        select(RecordTemplate).where(RecordTemplate.tenant_id == user.tenant_id).order_by(RecordTemplate.id.desc())
    )).scalars().all()
    return [TemplateOut.model_validate(t) for t in rows]


@router.post("", response_model=TemplateOut)
@audited("record_template.create", "record_template")
async def create_template(
    body: TemplateCreate,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> TemplateOut:
    t = RecordTemplate(
        tenant_id=user.tenant_id, name=body.name, description=body.description,
        fields=[f.model_dump() for f in body.fields], instructions=body.instructions,
        enabled=body.enabled, created_by=user.id,
    )
    db.add(t)
    await db.flush()
    return TemplateOut.model_validate(t)


@router.patch("/{template_id}", response_model=TemplateOut)
@audited("record_template.update", "record_template", id_arg="template_id")
async def update_template(
    template_id: int,
    body: TemplateUpdate,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> TemplateOut:
    t = await db.get(RecordTemplate, template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")
    data = body.model_dump(exclude_unset=True)
    if "fields" in data and data["fields"] is not None:
        data["fields"] = [f.model_dump() if hasattr(f, "model_dump") else f for f in body.fields]
    for k, v in data.items():
        setattr(t, k, v)
    await db.flush()
    return TemplateOut.model_validate(t)


@router.delete("/{template_id}")
@audited("record_template.delete", "record_template", id_arg="template_id")
async def delete_template(
    template_id: int,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    t = await db.get(RecordTemplate, template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")
    from sqlalchemy import delete as _del

    await db.execute(_del(RecordEntry).where(RecordEntry.template_id == template_id))
    await db.delete(t)
    await db.flush()
    return {"message": "已删除"}


@router.post("/extract")
@audited("record.extract", "record_entry")
async def extract(
    body: ExtractIn,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """从文本抽取结构化记录。save=True 时落库。"""
    from app.services.record_extract_service import extract_records

    t = await db.get(RecordTemplate, body.template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")
    if not body.text.strip():
        raise ValidationError("文本不能为空")
    try:
        rows = await extract_records(db, tenant_id=user.tenant_id, template=t, text=body.text)
    except ValueError as e:
        raise ValidationError(str(e))
    entries = []
    for row in rows:
        if body.save:
            e = RecordEntry(
                tenant_id=user.tenant_id, template_id=t.id, data=row,
                source_type=body.source_type, source_ref=body.source_ref,
                raw_text=body.text[:8000], created_by=user.id, status="draft",
            )
            db.add(e)
            await db.flush()
            entries.append({"id": e.id, "data": row, "status": "draft"})
        else:
            entries.append({"id": None, "data": row, "status": "draft"})
    return {"count": len(entries), "entries": entries}


@router.get("/{template_id}/entries")
async def list_entries(
    template_id: int,
    user: User = Depends(require_permission("record:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (await db.execute(
        select(RecordEntry).where(RecordEntry.template_id == template_id, RecordEntry.tenant_id == user.tenant_id)
        .order_by(RecordEntry.id.desc()).limit(500)
    )).scalars().all()
    return [{"id": e.id, "data": e.data, "source_type": e.source_type, "status": e.status} for e in rows]


@router.patch("/entries/{entry_id}")
async def update_entry(
    entry_id: int,
    body: EntryUpdate,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    e = await db.get(RecordEntry, entry_id)
    if not e or e.tenant_id != user.tenant_id:
        raise NotFoundError("记录不存在")
    e.data = body.data
    if body.status:
        e.status = body.status
    await db.flush()
    return {"message": "已保存"}


@router.delete("/entries/{entry_id}")
async def delete_entry(
    entry_id: int,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    e = await db.get(RecordEntry, entry_id)
    if not e or e.tenant_id != user.tenant_id:
        raise NotFoundError("记录不存在")
    await db.delete(e)
    await db.flush()
    return {"message": "已删除"}


@router.get("/{template_id}/export")
async def export_entries(
    template_id: int,
    fmt: str = "xlsx",
    user: User = Depends(require_permission("record:read")),
    db: AsyncSession = Depends(get_db),
):
    """导出台账为 xlsx/csv/md。"""
    t = await db.get(RecordTemplate, template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")
    rows = (await db.execute(
        select(RecordEntry).where(RecordEntry.template_id == template_id, RecordEntry.tenant_id == user.tenant_id)
        .order_by(RecordEntry.id.asc()).limit(2000)
    )).scalars().all()
    headers = [f.get("label") or f.get("name") for f in (t.fields or [])]
    keys = [f.get("name") for f in (t.fields or [])]
    table = [[(r.data or {}).get(k) for k in keys] for r in rows]

    if fmt == "csv":
        import csv as _csv

        buf = io.StringIO()
        w = _csv.writer(buf)
        w.writerow(headers)
        for row in table:
            w.writerow(["" if v is None else v for v in row])
        data, mime = buf.getvalue().encode("utf-8-sig"), "text/csv"
    elif fmt == "md":
        lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
        for row in table:
            lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
        data, mime = "\n".join(lines).encode("utf-8"), "text/markdown"
    else:
        from app.agents.tools.file_tools import _render

        data, mime = _render({"format": "xlsx", "rows": [headers] + table})
    safe = "".join(ch for ch in t.name if ch not in '\\/:*?"<>|')[:40]
    ext = "xlsx" if fmt not in ("csv", "md") else fmt
    from urllib.parse import quote

    fn = quote(f"{safe}-台账.{ext}")
    return StreamingResponse(
        io.BytesIO(data), media_type=mime,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"},
    )
