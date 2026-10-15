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
    EntryBatchIn,
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


@router.get("/docs/search")
async def search_docs(
    keyword: str | None = None,
    limit: int = 30,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """为「从文档录单」提供可选的文档：本租户已解析完成、有正文的文档（可按标题搜索）。"""
    from app.models import Document

    q = select(Document).where(
        Document.tenant_id == user.tenant_id,
        Document.status == "ready",
    )
    if keyword:
        q = q.where(Document.title.ilike(f"%{keyword}%"))
    rows = (await db.execute(q.order_by(Document.id.desc()).limit(max(1, min(limit, 100))))).scalars().all()
    return [{"id": d.id, "title": d.title, "kb_id": d.kb_id,
             "chars": len(d.content or "")} for d in rows if (d.content or "").strip()]


@router.post("/extract")
@audited("record.extract", "record_entry")
async def extract(
    body: ExtractIn,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """从文本或知识库文档抽取结构化记录。save=True 时落库。

    - text：直接粘贴的文本（通话记录/聊天/邮件）
    - doc_id：从知识库文档取全文（source_type 自动置为 document，source_ref=doc_id）
    """
    from app.services.record_extract_service import extract_records

    t = await db.get(RecordTemplate, body.template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")

    text = (body.text or "").strip()
    source_type = body.source_type
    source_ref = body.source_ref
    if body.doc_id is not None:
        from app.models import Document

        doc = await db.get(Document, int(body.doc_id))
        if not doc or doc.tenant_id != user.tenant_id:
            raise NotFoundError("文档不存在")
        text = (doc.content or "").strip()
        if not text:
            # 无解析全文时退而取分块拼合
            from app.models import Chunk

            chunks = (await db.execute(
                select(Chunk).where(Chunk.doc_id == doc.id).order_by(Chunk.id).limit(200)
            )).scalars().all()
            text = "\n".join(c.content for c in chunks if c.content).strip()
        if not text:
            raise ValidationError("该文档没有可用的文本内容（可能未解析完成）")
        source_type = "document"
        source_ref = str(doc.id)
    if not text:
        raise ValidationError("请提供要抽取的文本或选择知识库文档")
    try:
        rows = await extract_records(db, tenant_id=user.tenant_id, template=t, text=text)
    except ValueError as e:
        raise ValidationError(str(e))
    entries = []
    init_status = "confirmed" if body.auto_confirm else "draft"
    for row in rows:
        if body.save:
            e = RecordEntry(
                tenant_id=user.tenant_id, template_id=t.id, data=row,
                source_type=source_type, source_ref=source_ref,
                raw_text=text[:8000], created_by=user.id, status=init_status,
            )
            db.add(e)
            await db.flush()
            entries.append({"id": e.id, "data": row, "status": init_status})
        else:
            entries.append({"id": None, "data": row, "status": "draft"})
    return {"count": len(entries), "entries": entries, "source_type": source_type,
            "status": init_status}


@router.get("/{template_id}/entries")
async def list_entries(
    template_id: int,
    keyword: str | None = None,
    status: str | None = None,
    limit: int = 500,
    user: User = Depends(require_permission("record:read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """列出模板的记录。keyword 跨字段模糊匹配；status 过滤 draft/confirmed。"""
    t = await db.get(RecordTemplate, template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")
    q = select(RecordEntry).where(
        RecordEntry.template_id == template_id, RecordEntry.tenant_id == user.tenant_id
    )
    if status in ("draft", "confirmed"):
        q = q.where(RecordEntry.status == status)
    rows = (await db.execute(
        q.order_by(RecordEntry.id.desc()).limit(max(1, min(limit, 2000)))
    )).scalars().all()
    items = [{"id": e.id, "data": e.data, "source_type": e.source_type,
              "source_ref": e.source_ref, "raw_text": e.raw_text,
              "created_by": e.created_by, "created_at": e.created_at,
              "status": e.status} for e in rows]
    kw = (keyword or "").strip().lower()
    if kw:
        # 跨字段模糊匹配（含状态中文名，便于"草稿/已确认"也能搜）
        def _hit(e: dict) -> bool:
            blob = " ".join(str(v) for v in (e.get("data") or {}).values())
            blob += " " + ("已确认" if e["status"] == "confirmed" else "草稿")
            return kw in blob.lower()
        items = [e for e in items if _hit(e)]
    return items


@router.post("/entries/batch")
@audited("record.entry_batch", "record_entry")
async def batch_entries(
    body: EntryBatchIn,
    user: User = Depends(require_permission("record:manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量操作记录：delete（删除）/ confirm（确认）/ unconfirm（退回草稿）。"""
    action = (body.action or "").strip()
    if action not in ("delete", "confirm", "unconfirm"):
        raise ValidationError(f"不支持的批量操作：{action}")
    ids = [int(i) for i in (body.ids or [])][:1000]
    if not ids:
        raise ValidationError("请选择要操作的记录")
    rows = (await db.execute(
        select(RecordEntry).where(
            RecordEntry.id.in_(ids), RecordEntry.tenant_id == user.tenant_id
        )
    )).scalars().all()
    if not rows:
        return {"ok": True, "affected": 0, "message": "没有可操作的记录"}
    if action == "delete":
        for e in rows:
            await db.delete(e)
        msg = f"已删除 {len(rows)} 条记录"
    else:
        target = "confirmed" if action == "confirm" else "draft"
        for e in rows:
            e.status = target
        msg = f"已将 {len(rows)} 条记录{'确认' if action == 'confirm' else '退回草稿'}"
    await db.flush()
    return {"ok": True, "affected": len(rows), "message": msg}


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
    status: str | None = None,  # 可选：只导出 draft / confirmed
    user: User = Depends(require_permission("record:read")),
    db: AsyncSession = Depends(get_db),
):
    """导出台账为 xlsx/csv/md，可按状态过滤。"""
    t = await db.get(RecordTemplate, template_id)
    if not t or t.tenant_id != user.tenant_id:
        raise NotFoundError("模板不存在")
    eq = select(RecordEntry).where(
        RecordEntry.template_id == template_id, RecordEntry.tenant_id == user.tenant_id
    )
    if status in ("draft", "confirmed"):
        eq = eq.where(RecordEntry.status == status)
    rows = (await db.execute(eq.order_by(RecordEntry.id.asc()).limit(2000))).scalars().all()
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
