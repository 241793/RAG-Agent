"""文件处理内置工具：读取 / 列出 / 文本转换（read）+ 生成 / 改写 / 真转格式（write，HITL）。

write 工具经 HITL 确认后执行，产物落 storage 并登记 Artifact，回链到消息供下载。
所有办公库惰性 import，缺失时返回 is_error 而非崩溃。
"""
from __future__ import annotations

import io
import time
from pathlib import Path

from sqlalchemy import select

from app.agents.tools.base import ToolContext, ToolResult
from app.ingest.storage import get_storage

# 支持的文本抽取目标
_TEXT_TARGETS = {"md", "txt", "csv"}
# 需要结构化渲染（走专门的排版库）的格式；其余一律按纯文本直出
_STRUCT_FORMATS = {"docx", "xlsx", "pptx", "pdf"}
# 常见扩展名 → MIME（未列出的按 text/plain 或按扩展名推断）
_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "csv": "text/csv",
    "txt": "text/plain",
    "log": "text/plain",
    "html": "text/html",
    "htm": "text/html",
    "svg": "image/svg+xml",
    "json": "application/json",
    "js": "text/javascript",
    "mjs": "text/javascript",
    "ts": "text/typescript",
    "jsx": "text/jsx",
    "tsx": "text/tsx",
    "css": "text/css",
    "scss": "text/x-scss",
    "xml": "application/xml",
    "yml": "text/yaml",
    "yaml": "text/yaml",
    "py": "text/x-python",
    "sh": "text/x-sh",
    "java": "text/x-java",
    "go": "text/x-go",
    "rs": "text/x-rust",
    "c": "text/x-c",
    "cpp": "text/x-c++",
    "h": "text/x-c",
    "sql": "text/x-sql",
    "ini": "text/plain",
    "conf": "text/plain",
    "env": "text/plain",
    "vue": "text/x-vue",
    "rb": "text/x-ruby",
    "php": "text/x-php",
    "kt": "text/x-kotlin",
    "swift": "text/x-swift",
    "bat": "text/plain",
    "ps1": "text/plain",
    "toml": "text/plain",
}


def _ext_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _mime_for(ext: str) -> str:
    """扩展名 → MIME；未收录的按 text/plain 兜底。"""
    return _MIME.get(ext, "text/plain")


def _check_tenant_key(ctx: ToolContext, file_key: str) -> str | None:
    """校验 file_key 属于当前租户，返回错误信息或 None。"""
    if not file_key.startswith(f"{ctx.tenant_id}/"):
        return "无权访问该文件"
    return None


def _stem(name: str) -> str:
    return Path(name).stem or "file"


# ==================== Markdown 表格解析（生成 docx/pdf 用）====================
def _parse_md_table(lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    """把连续的 markdown 表格行解析为 (表头, 数据行)。非表格返回 None。"""
    rows: list[list[str]] = []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            return None
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return None
    # 第二行须是分隔行（--- | :--: 等）
    sep = rows[1]
    if not all(set(c) <= set("-: ") and c for c in sep):
        return None
    return rows[0], rows[2:]


def _is_table_start(line: str, nxt: str) -> bool:
    return line.strip().startswith("|") and nxt.strip().startswith("|") and set(nxt.strip().strip("|").replace("|", "")) <= set("-: ")


def _render_docx(content: str) -> bytes:
    import docx

    doc = docx.Document()
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].rstrip()
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        # 表格块
        if _is_table_start(s, nxt):
            block = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append(lines[j]); j += 1
            parsed = _parse_md_table(block)
            if parsed:
                header, body = parsed
                ncol = max([len(header)] + [len(r) for r in body]) if body else len(header)
                t = doc.add_table(rows=1, cols=ncol)
                t.style = "Light Grid Accent 1"
                for ci, c in enumerate(header):
                    if ci < ncol:
                        t.rows[0].cells[ci].text = c
                for r in body:
                    cells = t.add_row().cells
                    for ci in range(ncol):
                        cells[ci].text = r[ci] if ci < len(r) else ""
                i = j
                continue
        if s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.startswith("- ") or s.startswith("* "):
            doc.add_paragraph(s[2:], style="List Bullet")
        elif s.startswith("> "):
            doc.add_paragraph(s[2:], style="Intense Quote")
        else:
            doc.add_paragraph(s)
        i += 1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _render_xlsx(content: str, rows: list | None,
                 charts: list | None = None, sheet_name: str | None = None) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    if sheet_name:
        ws.title = str(sheet_name)[:31]
    if rows:
        for row in rows:
            ws.append(list(row))
    else:
        for ln in content.split("\n"):
            cells = ln.split(",") if "," in ln else ln.split("\t")
            ws.append([c.strip() for c in cells])
    # 图表：rows 首行为表头时，分类用第 1 列、系列用其余列
    for ch in (charts or []):
        try:
            ctype = str(ch.get("type") or "bar").lower()
            title = str(ch.get("title") or "")
            anchor = str(ch.get("anchor") or "H2")
            data = ch.get("data")  # 可选：显式 {categories:[], series:[{name, values:[]}]}
            existing = ws.max_row
            if data and data.get("series"):
                cats = data.get("categories") or []
                start = existing + 2
                ws.cell(row=start, column=1, value=ch.get("category_title") or "类别")
                for j, s in enumerate(data["series"], start=2):
                    ws.cell(row=start, column=j, value=s.get("name") or f"系列{j-1}")
                for i, cval in enumerate(cats):
                    ws.cell(row=start + 1 + i, column=1, value=cval)
                    for j, s in enumerate(data["series"], start=2):
                        vals = s.get("values") or []
                        if i < len(vals):
                            ws.cell(row=start + 1 + i, column=j, value=vals[i])
                min_col, max_col = 1, 1 + len(data["series"])
                min_row, max_row = start, start + len(cats)
            else:
                min_col, min_row, max_col, max_row = 1, 1, ws.max_column, ws.max_row
            from openpyxl.chart import BarChart, LineChart, PieChart, Reference

            ref = Reference(ws, min_col=min_col, min_row=min_row, max_col=max_col, max_row=max_row)
            chart = {"bar": BarChart, "line": LineChart, "pie": PieChart}.get(ctype, BarChart)()
            chart.title = title or None
            chart.add_data(ref, titles_from_data=True)
            ws.add_chart(chart, anchor)
        except Exception:  # noqa: BLE001
            continue  # 单个图表失败不影响整体导出
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _render_pptx(content: str, slides: list | None) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches  # noqa: F401

    prs = Presentation()
    if slides:
        for s in slides:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = str(s.get("title") or "")
            body = slide.placeholders[1].text_frame
            body.text = ""
            for b in (s.get("bullets") or []):
                p = body.add_paragraph()
                p.text = str(b)
    else:
        for block in content.split("\n\n"):
            lines = [x for x in block.split("\n") if x.strip()]
            if not lines:
                continue
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = lines[0].lstrip("# ").strip()
            body = slide.placeholders[1].text_frame
            body.text = ""
            for ln in lines[1:]:
                p = body.add_paragraph()
                p.text = ln.lstrip("- ").strip()
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _register_cjk_font() -> str:
    """注册中文字体，返回字体名；找不到则回退 Helvetica。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        ("SimSun", r"C:\Windows\Fonts\simsun.ttc"),
        ("MicrosoftYaHei", r"C:\Windows\Fonts\msyh.ttc"),
        ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ("WenQuanYi", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ]
    for name, path in candidates:
        try:
            if Path(path).is_file():
                pdfmetrics.registerFont(TTFont(name, path))
                return name
        except Exception:  # noqa: BLE001
            continue
    return "Helvetica"


def _render_pdf(content: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    font = _register_cjk_font()
    styles = getSampleStyleSheet()
    for s in styles.byName.values():
        s.fontName = font
    doc = SimpleDocTemplate(buf, pagesize=A4)
    flow = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].rstrip()
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _is_table_start(s, nxt):
            block = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append(lines[j]); j += 1
            parsed = _parse_md_table(block)
            if parsed:
                header, body = parsed
                data = [header] + body
                t = Table(data, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTNAME", (0, 0), (-1, -1), font),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]))
                flow.append(t)
                flow.append(Spacer(1, 8))
            i = j
            continue
        if s.startswith("# "):
            flow.append(Paragraph(s[2:], styles["Heading1"]))
        elif s.startswith("## "):
            flow.append(Paragraph(s[3:], styles["Heading2"]))
        elif s.startswith("### "):
            flow.append(Paragraph(s[4:], styles["Heading3"]))
        elif s.startswith("- ") or s.startswith("* "):
            flow.append(Paragraph("• " + s[2:].replace("<", "&lt;").replace(">", "&gt;"), styles["BodyText"]))
        elif not s:
            flow.append(Spacer(1, 8))
        else:
            flow.append(Paragraph(s.replace("<", "&lt;").replace(">", "&gt;"), styles["BodyText"]))
        i += 1
    doc.build(flow)
    return buf.getvalue()


def _render(args: dict, fmt: str | None = None) -> tuple[bytes, str]:
    """按格式渲染。fmt 缺省时从 args['format'] 取（兼容旧调用）。"""
    if not fmt:
        fmt = str(args.get("format") or "txt").lower().lstrip(".")
    content = str(args.get("content") or "")
    if fmt == "docx":
        return _render_docx(content), _MIME["docx"]
    if fmt == "xlsx":
        return _render_xlsx(content, args.get("rows"), charts=args.get("charts"),
                            sheet_name=args.get("sheet_name")), _MIME["xlsx"]
    if fmt == "pptx":
        return _render_pptx(content, args.get("slides")), _MIME["pptx"]
    if fmt == "pdf":
        return _render_pdf(content), _MIME["pdf"]
    # 其余格式（md/csv/txt/html/svg/json/js/css/… 及任何未知扩展名）：纯文本直出
    return content.encode("utf-8"), _mime_for(fmt)


def _save_artifact(ctx: ToolContext, filename: str, data: bytes, mime: str):
    """落盘 + 登记 Artifact，返回 (file_key, artifact_id, size)。"""
    from app.models import Artifact

    storage = get_storage()
    file_key, chash = storage.save(tenant_id=ctx.tenant_id, filename=filename, data=data)
    art = Artifact(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        conversation_id=ctx.conversation_id,
        message_id=None,
        file_key=file_key,
        file_name=filename,
        file_ext=Path(filename).suffix.lower().lstrip("."),
        mime=mime,
        size=len(data),
        source="generated",
        content_hash=chash,
    )
    ctx.db.add(art)
    return file_key, art, chash


# ==================== read 类 ====================
class ReadFileTool:
    name = "read_file"
    description = "读取对话中上传的文件或知识库文档的文本内容。用于分析用户提供的文件。"
    required_permission = "file:read"
    kind = "read"
    parameters = {
        "type": "object",
        "properties": {
            "file_key": {"type": "string", "description": "附件/产物的 file_key（从对话上下文获取）"},
            "doc_id": {"type": "integer", "description": "或知识库文档 id"},
            "max_chars": {"type": "integer", "description": "最大读取字符数，默认 100000", "default": 100000},
        },
    }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.ingest.parsers.parser import parse_file

        max_chars = int(args.get("max_chars") or 100000)
        path = None
        if args.get("file_key"):
            fk = str(args["file_key"])
            err = _check_tenant_key(ctx, fk)
            if err:
                return ToolResult(content=err, is_error=True)
            p = get_storage().path(fk)
            if not p.is_file():
                return ToolResult(content="文件不存在", is_error=True)
            path = p
        elif args.get("doc_id"):
            from app.models import Document

            doc = await ctx.db.get(Document, int(args["doc_id"]))
            if not doc or doc.tenant_id != ctx.tenant_id or not doc.file_key:
                return ToolResult(content="文档不存在", is_error=True)
            path = get_storage().path(doc.file_key)
            if not path.is_file():
                return ToolResult(content="文件已丢失", is_error=True)
        else:
            return ToolResult(content="需提供 file_key 或 doc_id", is_error=True)

        try:
            parsed = parse_file(path, path.suffix.lower().lstrip("."))
            return ToolResult(content=parsed.text[:max_chars], data={"char_count": len(parsed.text), "path": path.name})
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"解析失败：{str(e)[:200]}", is_error=True)


class ListConversationFilesTool:
    name = "list_conversation_files"
    description = "列出当前对话中用户上传的附件与 AI 生成的产物（含 file_key，可用于 read_file/下载）。"
    required_permission = "file:read"
    kind = "read"
    parameters = {
        "type": "object",
        "properties": {"conversation_id": {"type": "integer", "description": "会话 id，默认当前会话"}},
    }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.models import Artifact, Message

        conv_id = int(args.get("conversation_id") or ctx.conversation_id or 0)
        lines: list[str] = []
        # 会话消息里的附件
        rows = (
            await ctx.db.execute(
                select(Message).where(Message.conversation_id == conv_id, Message.attachments.isnot(None))
            )
        ).scalars().all()
        for m in rows:
            for a in (m.attachments or []):
                lines.append(f"[附件] {a.get('name')} | type={a.get('type')} | file_key={a.get('file_key')}")
        # 产物
        arts = (
            await ctx.db.execute(
                select(Artifact).where(
                    Artifact.conversation_id == conv_id, Artifact.tenant_id == ctx.tenant_id
                )
            )
        ).scalars().all()
        for ar in arts:
            lines.append(f"[产物] {ar.file_name} | id={ar.id} | file_key={ar.file_key}")
        if not lines:
            return ToolResult(content="（当前会话暂无文件）", data={"count": 0})
        return ToolResult(content="\n".join(lines), data={"count": len(lines)})


class ConvertFileTool:
    name = "convert_file"
    description = "把对话中的文件（pdf/docx/xlsx/pptx 等）抽取为文本/markdown/csv，用于分析其内容。"
    required_permission = "file:read"
    kind = "read"
    parameters = {
        "type": "object",
        "properties": {
            "file_key": {"type": "string"},
            "target": {"type": "string", "enum": ["md", "txt", "csv"], "default": "md"},
        },
        "required": ["file_key"],
    }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.ingest.parsers.parser import parse_file

        fk = str(args.get("file_key") or "")
        if not fk:
            return ToolResult(content="需提供 file_key", is_error=True)
        err = _check_tenant_key(ctx, fk)
        if err:
            return ToolResult(content=err, is_error=True)
        p = get_storage().path(fk)
        if not p.is_file():
            return ToolResult(content="文件不存在", is_error=True)
        target = str(args.get("target") or "md").lower()
        ext = p.suffix.lower().lstrip(".")
        try:
            # 表格类源 + target=csv → 真 CSV（保留行列结构，而非把表格拍成文本）
            if target == "csv" and ext in ("xlsx", "xlsm", "csv"):
                text = _to_csv(p, ext)
            else:
                parsed = parse_file(p, ext)
                text = parsed.text[:100000]
                if target == "txt":
                    text = _strip_markdown(text)
            return ToolResult(content=text, data={"target": target, "source_ext": ext})
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"转换失败：{str(e)[:200]}", is_error=True)


def _to_csv(path, ext: str) -> str:
    """把 xlsx/csv 源转成 CSV 文本（多工作表以注释行分隔）。"""
    import csv as _csv
    import io

    if ext == "csv":
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        rows = list(_csv.reader(io.StringIO(raw)))
        buf = io.StringIO()
        _csv.writer(buf).writerows(rows)
        return buf.getvalue()[:100000]

    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    buf = io.StringIO()
    for idx, ws in enumerate(wb.worksheets):
        if idx:
            buf.write("\n")
        buf.write(f"# 工作表: {ws.title}\n")
        w = _csv.writer(buf)
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else c for c in row]
            while cells and cells[-1] == "":
                cells.pop()
            if any(str(c).strip() for c in cells):
                w.writerow(cells)
    wb.close()
    return buf.getvalue()[:100000]


def _strip_markdown(text: str) -> str:
    """粗略去除 markdown 标记（标题 #、粗体 **、行内代码 `）。"""
    import re as _re

    out = _re.sub(r"^#{1,6}\s*", "", text, flags=_re.M)
    out = out.replace("**", "").replace("__", "")
    out = _re.sub(r"`([^`]*)`", r"\1", out)
    return out


# ==================== write 类（HITL）====================
class _WriteToolMixin:
    kind = "write"

    def summarize(self, args: dict) -> str:
        return f"将调用 {self.name}"

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return await self.execute(args, ctx)

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError


class GenerateFileTool(_WriteToolMixin):
    name = "generate_file"
    description = (
        "根据内容生成文件供用户下载。**按 filename 的扩展名自动判断格式**，无需手动指定。\n"
        "支持任意常见类型：\n"
        "- 办公文档：.docx / .pdf（content 传 markdown，会自动排版）、"
        ".xlsx（用 rows 传二维数组）、.pptx（用 slides 传 [{title,bullets}]）\n"
        "- 网页/代码/文本：.html / .svg / .json / .js / .css / .xml / .py / .md / .csv / .txt 等"
        "（content 传原文，原样写出）\n"
        "调用示例：要生成一个网页动画，就传 filename=\"anim.html\"（不要用 .txt），"
        "content 放完整 HTML/SVG 源码。"
    )
    required_permission = "file:write"
    parameters = {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "文件名（务必含正确扩展名，如 index.html、report.docx）"},
            "content": {"type": "string", "description": "正文内容；办公文档传 markdown，网页/代码/文本传原文"},
            "format": {"type": "string", "description": "可选。留空则按 filename 扩展名自动判断；仅当文件名无扩展名时需要指定"},
            "rows": {"type": "array", "items": {"type": "array", "items": {}}, "description": "xlsx 数据（二维数组）"},
            "slides": {"type": "array", "items": {"type": "object"}, "description": "pptx 幻灯片 [{title,bullets}]"},
        },
        "required": ["filename"],
    }

    def summarize(self, args: dict) -> str:
        return f"生成文件「{args.get('filename')}」"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        filename = str(args.get("filename") or "").strip()
        # 格式解析优先级：文件名扩展名 > 显式 format > 兜底 txt
        ext = _ext_of(filename)
        fmt = ext or str(args.get("format") or "").lower().lstrip(".")
        if fmt == "markdown":
            fmt = "md"
        fmt = fmt or "txt"
        if not filename:
            filename = f"output.{fmt}"
        elif not Path(filename).suffix:
            # 文件名无扩展名：补上解析出的格式
            filename = f"{filename}.{fmt}"
        try:
            data, mime = _render(args, fmt)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"生成失败：{str(e)[:200]}", is_error=True)
        file_key, art, _ = _save_artifact(ctx, filename, data, mime)
        await ctx.db.flush()
        return ToolResult(
            content=f"已生成文件：{filename}（{len(data)} 字节，可下载）",
            data={"file_key": file_key, "artifact_id": art.id, "name": filename, "mime": mime,
                  "size": len(data), "url": f"/api/v1/chat/attachments/{file_key}"},
        )


class EditFileTool(_WriteToolMixin):
    name = "edit_file"
    description = "读取用户上传的 docx/xlsx 文件，按指令改写后另存为新文件供下载。"
    required_permission = "file:write"
    parameters = {
        "type": "object",
        "properties": {
            "file_key": {"type": "string", "description": "源文件 file_key"},
            "instructions": {"type": "string", "description": "改写内容（纯文本追加/替换说明）"},
            "output_filename": {"type": "string", "description": "输出文件名"},
        },
        "required": ["file_key", "instructions"],
    }

    def summarize(self, args: dict) -> str:
        return f"改写文件 {args.get('file_key')} → {args.get('output_filename') or '新文件'}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        fk = str(args.get("file_key") or "")
        err = _check_tenant_key(ctx, fk)
        if err:
            return ToolResult(content=err, is_error=True)
        src = get_storage().path(fk)
        if not src.is_file():
            return ToolResult(content="源文件不存在", is_error=True)
        ext = src.suffix.lower().lstrip(".")
        out_name = str(args.get("output_filename") or f"{_stem(src.name)}-edited.{ext}")
        if not out_name.lower().endswith(f".{ext}"):
            out_name = f"{out_name}.{ext}"
        try:
            if ext == "docx":
                import docx

                doc = docx.Document(str(src))
                for ln in str(args.get("instructions") or "").split("\n"):
                    doc.add_paragraph(ln)
                buf = io.BytesIO()
                doc.save(buf)
                data = buf.getvalue()
            elif ext == "xlsx":
                import openpyxl

                wb = openpyxl.load_workbook(str(src))
                ws = wb.active
                for ln in str(args.get("instructions") or "").split("\n"):
                    ws.append([c.strip() for c in ln.split(",")])
                buf = io.BytesIO()
                wb.save(buf)
                data = buf.getvalue()
            else:
                return ToolResult(content=f"暂不支持改写 .{ext}（仅 docx/xlsx）", is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"改写失败：{str(e)[:200]}", is_error=True)
        file_key, art, _ = _save_artifact(ctx, out_name, data, _MIME.get(ext, "application/octet-stream"))
        await ctx.db.flush()
        return ToolResult(
            content=f"已生成改写文件：{out_name}（可下载）",
            data={"file_key": file_key, "artifact_id": art.id, "name": out_name,
                  "mime": _MIME.get(ext), "size": len(data), "url": f"/api/v1/chat/attachments/{file_key}"},
        )


class ConvertFileToTool(_WriteToolMixin):
    name = "convert_file_to"
    description = "把文件真转格式另存（如 xlsx→csv、docx→pdf）。docx→pdf 需系统装 LibreOffice，否则降级为文本重排。"
    required_permission = "file:write"
    parameters = {
        "type": "object",
        "properties": {
            "file_key": {"type": "string"},
            "target_ext": {"type": "string", "enum": ["pdf", "csv", "md", "txt", "xlsx"]},
        },
        "required": ["file_key", "target_ext"],
    }

    def summarize(self, args: dict) -> str:
        return f"转换文件 {args.get('file_key')} → .{args.get('target_ext')}"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        from app.ingest.parsers.parser import parse_file

        fk = str(args.get("file_key") or "")
        target = str(args.get("target_ext") or "").lower()
        err = _check_tenant_key(ctx, fk)
        if err:
            return ToolResult(content=err, is_error=True)
        src = get_storage().path(fk)
        if not src.is_file():
            return ToolResult(content="源文件不存在", is_error=True)
        stem = _stem(src.name)
        try:
            if target == "pdf":
                # 优先 LibreOffice 真转；否则文本重排
                import shutil
                import subprocess
                import tempfile

                soffice = shutil.which("soffice") or shutil.which("libreoffice")
                if soffice:
                    with tempfile.TemporaryDirectory() as td:
                        proc = subprocess.run(
                            [soffice, "--headless", "--convert-to", "pdf", str(src), "--outdir", td],
                            capture_output=True, timeout=60,
                        )
                        out = Path(td) / f"{stem}.pdf"
                        if proc.returncode != 0 or not out.is_file():
                            return ToolResult(content="LibreOffice 转换失败", is_error=True)
                        data = out.read_bytes()
                    note = "（LibreOffice 保真转换）"
                else:
                    parsed = parse_file(src, src.suffix.lower().lstrip("."))
                    data = _render_pdf(parsed.text)
                    note = "（无 LibreOffice，已降级为文本重排 PDF，原格式丢失）"
                out_name = f"{stem}.pdf"
            elif target in ("csv", "md", "txt"):
                parsed = parse_file(src, src.suffix.lower().lstrip("."))
                data = parsed.text.encode("utf-8")
                out_name = f"{stem}.{target}"
                note = ""
            elif target == "xlsx":
                parsed = parse_file(src, src.suffix.lower().lstrip("."))
                data = _render_xlsx(parsed.text, None)
                out_name = f"{stem}.xlsx"
                note = ""
            else:
                return ToolResult(content=f"不支持转换到 {target}", is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"转换失败：{str(e)[:200]}", is_error=True)
        mime = _MIME.get(target, "application/octet-stream")
        file_key, art, _ = _save_artifact(ctx, out_name, data, mime)
        await ctx.db.flush()
        return ToolResult(
            content=f"已生成 {out_name}{note}",
            data={"file_key": file_key, "artifact_id": art.id, "name": out_name,
                  "mime": mime, "size": len(data), "url": f"/api/v1/chat/attachments/{file_key}"},
        )


class AnalyzeTableTool:
    name = "analyze_table"
    description = (
        "对 Excel/CSV 表格做数据问答与统计。把表格解析成结构化行列（含列名、行数），"
        "可对指定列做求和/平均/最大/最小/计数/分组统计。适合「总额多少」「按类别汇总」这类问题。"
    )
    required_permission = "file:read"
    kind = "read"
    parameters = {
        "type": "object",
        "properties": {
            "file_key": {"type": "string", "description": "表格附件的 file_key（从对话上下文获取）"},
            "doc_id": {"type": "integer", "description": "或知识库文档 id"},
            "column": {"type": "string", "description": "要统计的列名（数值列做 sum/avg 等）"},
            "agg": {"type": "string", "enum": ["sum", "avg", "max", "min", "count", "group"],
                    "description": "聚合方式；group 需配合 group_by"},
            "group_by": {"type": "string", "description": "group 聚合时的分组列名"},
            "filter_col": {"type": "string", "description": "可选：按某列过滤"},
            "filter_value": {"type": "string", "description": "可选：过滤值（包含匹配）"},
            "limit": {"type": "integer", "default": 20, "description": "预览/分组返回条数"},
        },
    }

    def _load_rows(self, path) -> tuple[list[str], list[dict]]:
        """读表格 → (表头, 行字典列表)。支持 xlsx/xls/csv。"""
        ext = path.suffix.lower().lstrip(".")
        if ext in ("xlsx", "xls"):
            from openpyxl import load_workbook

            wb = load_workbook(str(path), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
            if not rows:
                return [], []
            header = [str(c) if c is not None else f"col{i}" for i, c in enumerate(rows[0])]
            out = []
            for r in rows[1:]:
                if r is None or all(c is None for c in r):
                    continue
                out.append({header[i]: (r[i] if i < len(r) else None) for i in range(len(header))})
            return header, out
        # csv / txt
        import csv as _csv

        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        reader = list(_csv.reader(text.splitlines()))
        if not reader:
            return [], []
        header = reader[0]
        return header, [dict(zip(header, r)) for r in reader[1:] if any(x.strip() for x in r)]

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = None
        if args.get("file_key"):
            fk = str(args["file_key"])
            err = _check_tenant_key(ctx, fk)
            if err:
                return ToolResult(content=err, is_error=True)
            p = get_storage().path(fk)
            if not p.is_file():
                return ToolResult(content="文件不存在", is_error=True)
            path = p
        elif args.get("doc_id"):
            from app.models import Document

            doc = await ctx.db.get(Document, int(args["doc_id"]))
            if not doc or doc.tenant_id != ctx.tenant_id or not doc.file_key:
                return ToolResult(content="文档不存在", is_error=True)
            path = get_storage().path(doc.file_key)
            if not path.is_file():
                return ToolResult(content="文件已丢失", is_error=True)
        else:
            return ToolResult(content="需提供 file_key 或 doc_id", is_error=True)

        if path.suffix.lower().lstrip(".") not in ("xlsx", "xls", "csv", "txt"):
            return ToolResult(content="仅支持 xlsx/xls/csv 表格", is_error=True)
        try:
            header, rows = self._load_rows(path)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"读取表格失败：{str(e)[:200]}", is_error=True)
        if not header:
            return ToolResult(content="表格为空", is_error=True)

        # 可选过滤
        fcol, fval = args.get("filter_col"), args.get("filter_value")
        if fcol and fval is not None:
            rows = [r for r in rows if str(r.get(fcol, "")).lower().find(str(fval).lower()) >= 0]

        def _num(v):
            try:
                return float(str(v).replace(",", ""))
            except (ValueError, TypeError):
                return None

        col = args.get("column")
        agg = args.get("agg")
        if agg and col:
            vals = [n for n in (_num(r.get(col)) for r in rows) if n is not None]
            if agg == "group":
                gb = args.get("group_by")
                if not gb:
                    return ToolResult(content="group 聚合需提供 group_by", is_error=True)
                groups: dict[str, list[float]] = {}
                for r in rows:
                    n = _num(r.get(col))
                    if n is None:
                        continue
                    groups.setdefault(str(r.get(gb, "?")), []).append(n)
                lines = [f"按「{gb}」汇总「{col}」（共 {len(rows)} 行）："]
                for k, vs in sorted(groups.items(), key=lambda x: -sum(x[1]))[:int(args.get("limit") or 20)]:
                    lines.append(f"  {k}: 合计 {sum(vs):g}（{len(vs)} 行，均值 {sum(vs)/len(vs):g}）")
                return ToolResult(content="\n".join(lines),
                                  data={"groups": len(groups), "rows": len(rows)})
            if not vals:
                return ToolResult(content=f"列「{col}」没有可统计的数值", is_error=True)
            if agg == "sum":
                res = f"「{col}」合计 = {sum(vals):g}"
            elif agg == "avg":
                res = f"「{col}」平均 = {sum(vals)/len(vals):g}"
            elif agg == "max":
                res = f"「{col}」最大 = {max(vals):g}"
            elif agg == "min":
                res = f"「{col}」最小 = {min(vals):g}"
            else:  # count
                res = f"「{col}」有效数值行数 = {len(vals)}"
            return ToolResult(content=f"{res}（基于 {len(rows)} 行）",
                              data={"value": sum(vals) if agg == "sum" else None, "count": len(vals)})

        # 无聚合：返回结构概览 + 前 N 行
        limit = int(args.get("limit") or 20)
        sample = rows[:limit]
        lines = [f"表格共 {len(rows)} 行，列：{', '.join(header)}",
                 "前几行预览："]
        for r in sample:
            lines.append("  " + " | ".join(str(r.get(h, "")) for h in header[:10]))
        return ToolResult(content="\n".join(lines),
                          data={"rows": len(rows), "columns": header, "preview": sample})


FILE_TOOLS = [
    ReadFileTool(),
    ListConversationFilesTool(),
    ConvertFileTool(),
    GenerateFileTool(),
    EditFileTool(),
    ConvertFileToTool(),
    AnalyzeTableTool(),
]