"""办公文档增强渲染：docx / xlsx / pdf 的专业排版（封面、页眉页脚、页码、目录、表格样式、多表、列宽、格式、冻结、条件色）。

对外入口：
- render_docx(content, meta=None)  meta 支持 {title, subtitle, author, date, header, footer, cover, toc, font}
- render_xlsx(content, rows=None, charts=None, sheet_name=None, sheets=None, options=None)
- render_pdf(content, meta=None)   meta 支持 {title, subtitle, author, date, header, footer, cover}

设计目标：让 AI 只填内容/结构，排版交给这里，产出接近人工排版的观感。
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

# ---------- Markdown 表格解析（与 file_tools 一致） ----------
def _is_table_start(line: str, nxt: str) -> bool:
    return line.strip().startswith("|") and nxt.strip().startswith("|") and set(nxt.strip().strip("|").replace("|", "")) <= set("-: ")


def _parse_md_table(block: list[str]) -> tuple[list[str], list[list[str]]] | None:
    rows = []
    for ln in block:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return None
    header = rows[0]
    body = [r for r in rows[2:]]  # 跳过分隔行
    return header, body


# ==================== DOCX ====================
def _docx_set_cjk(doc, font_name: str = "微软雅黑", size: int | None = None) -> None:
    """把全文（含样式）中文字体统一，避免默认宋体观感。"""
    from docx.oxml.ns import qn
    from docx.shared import Pt

    def _apply(style):
        try:
            style.font.name = font_name
            rpr = style.element.get_or_add_rPr()
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = rpr.makeelement(qn("w:rFonts"), {})
                rpr.append(rfonts)
            rfonts.set(qn("w:eastAsia"), font_name)
            if size:
                style.font.size = Pt(size)
        except Exception:  # noqa: BLE001
            pass

    for name in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Title", "Quote"):
        try:
            _apply(doc.styles[name])
        except KeyError:
            continue


def _docx_add_page_number(doc) -> None:
    """页脚居中插入「第 X 页」域。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    footer = doc.sections[0].footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("第 ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run._r.addnext(fld)
    p.add_run(" 页")


def _docx_add_toc(doc) -> None:
    """插入目录域（TOC \\o "1-3"）。Word 打开后按 F9 / 右键「更新域」即生成目录。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "（此处为目录，打开后按 F9 或右键「更新域」生成）"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    r = run._r
    r.append(begin); r.append(instr); r.append(sep); r.append(placeholder); r.append(end)
    doc.add_paragraph()


def _docx_cover(doc, title: str, subtitle: str = "", author: str = "", date: str = "") -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    for _ in range(4):
        doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(title)
    r.bold = True
    r.font.size = Pt(32)
    r.font.color.rgb = RGBColor(0x1E, 0x3A, 0x8A)
    if subtitle:
        s = doc.add_paragraph()
        s.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rs = s.add_run(subtitle)
        rs.font.size = Pt(16)
        rs.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
    for _ in range(8):
        doc.add_paragraph()
    for line in (author, date):
        if line:
            a = doc.add_paragraph()
            a.alignment = WD_ALIGN_PARAGRAPH.CENTER
            ra = a.add_run(line)
            ra.font.size = Pt(12)
            ra.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
    doc.add_page_break()


def _docx_table(doc, header: list[str], body: list[list[str]]) -> None:
    """带样式的表格：表头底纹、边框、列宽自适应。"""
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Pt, RGBColor

    ncol = max([len(header)] + [len(r) for r in body]) if body else len(header)
    t = doc.add_table(rows=1, cols=ncol)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER

    def _shade(cell, hex6: str):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), hex6)
        tcPr.append(shd)

    for ci in range(ncol):
        cell = t.rows[0].cells[ci]
        cell.text = header[ci] if ci < len(header) else ""
        _shade(cell, "1E3A8A")
        for para in cell.paragraphs:
            for run in para.runs:
                run.font.bold = True
                run.font.size = Pt(10.5)
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for ri, r in enumerate(body):
        cells = t.add_row().cells
        for ci in range(ncol):
            cells[ci].text = r[ci] if ci < len(r) else ""
            if ri % 2 == 1:
                _shade(cells[ci], "F1F5F9")
            for para in cells[ci].paragraphs:
                for run in para.runs:
                    run.font.size = Pt(10.5)
    doc.add_paragraph()


def render_docx(content: str, meta: dict | None = None) -> bytes:
    import docx
    from docx.shared import Pt, RGBColor

    meta = meta or {}
    doc = docx.Document()
    _docx_set_cjk(doc, meta.get("font") or "微软雅黑")
    # 页边距略收紧
    try:
        for sec in doc.sections:
            from docx.shared import Cm
            sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.2)
            sec.left_margin = Cm(2.4); sec.right_margin = Cm(2.4)
    except Exception:  # noqa: BLE001
        pass

    # 页眉
    if meta.get("header"):
        hp = doc.sections[0].header.paragraphs[0]
        hr = hp.add_run(str(meta["header"]))
        hr.font.size = Pt(9)
        hr.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
    # 封面
    if meta.get("cover"):
        _docx_cover(doc, str(meta.get("title") or ""), str(meta.get("subtitle") or ""),
                    str(meta.get("author") or ""), str(meta.get("date") or ""))
    elif meta.get("title"):
        h = doc.add_heading(str(meta["title"]), level=0)
        h.alignment = 1  # center

    # 目录（可选）
    if meta.get("toc"):
        try:
            _docx_add_toc(doc)
        except Exception:  # noqa: BLE001
            pass

    # 正文（markdown 子集）
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
                _docx_table(doc, parsed[0], parsed[1])
            i = j
            continue
        if s.startswith("#### "):
            doc.add_heading(s[5:], level=4)
        elif s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.startswith("- ") or s.startswith("* "):
            doc.add_paragraph(s[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s", s):
            doc.add_paragraph(re.sub(r"^\d+\.\s", "", s), style="List Number")
        elif s.startswith("> "):
            doc.add_paragraph(s[2:], style="Intense Quote")
        elif s.strip() == "---":
            doc.add_paragraph("─" * 20).alignment = 1
        else:
            doc.add_paragraph(s)
        i += 1

    # 页脚页码
    try:
        _docx_add_page_number(doc)
    except Exception:  # noqa: BLE001
        pass

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ==================== XLSX ====================
def _xlsx_fmt_width(value, fmt: str | None) -> int:
    """按数字格式估算单元格显示宽度（字符数），避免 autosize 后仍显示 ####。"""
    if value is None or not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0
    f = fmt or "General"
    try:
        if "%" in f:
            dec = f.count("0", f.find(".") + 1, f.find("%")) if "." in f else 0
            s = f"{value * 100:,.{dec}f}%"
        elif "General" in f:
            s = str(value)
        else:
            dec = len(f.split(".")[1]) if "." in f else 0
            s = f"{value:,.{dec}f}"
    except Exception:  # noqa: BLE001
        return 0
    return len(s)


def _xlsx_autosize(ws, min_w: int = 8, max_w: int = 48) -> None:
    for col in ws.columns:
        width = min_w
        letter = None
        for cell in col:
            try:
                letter = cell.column_letter
            except Exception:  # noqa: BLE001
                continue
            v = cell.value
            if v is None:
                continue
            # 中文按 2 宽度计
            s = str(v)
            w = sum(2 if ord(c) > 0x2E80 else 1 for c in s) + 2
            # 数字格式（千分位/百分比/小数）会加宽显示，取格式后宽度
            fw = _xlsx_fmt_width(v, getattr(cell, "number_format", None))
            if fw:
                w = max(w, fw + 2)
            width = max(width, w)
        if letter:
            ws.column_dimensions[letter].width = min(width, max_w)


def _xlsx_style_header(ws, row: int = 1) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill("solid", fgColor="1E3A8A")
    for cell in ws[row]:
        if cell.value is None:
            continue
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _xlsx_append_table(ws, rows: list[list], start_row: int = 1, header: bool = True,
                       number_formats: dict | None = None, freeze: bool = True) -> int:
    """把二维数组写入工作表（从 start_row 起）。返回结束行。"""
    r = start_row
    for row in rows:
        ws.append(list(row))
        r += 1
    if header and rows:
        _xlsx_style_header(ws, start_row)
    if number_formats:
        for col_letter, fmt in number_formats.items():
            for cell in ws[col_letter]:
                if cell.row >= start_row:
                    cell.number_format = fmt
    if freeze and header:
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    return r


def _xlsx_add_charts(ws, charts: list | None) -> None:
    """图表。两种数据来源：

    - 显式 data:{categories, series:[{name, values}]} → 在工作表下方另写数据块再引用；
    - 不传 data → 直接引用工作表现有表格（首行表头作系列名、首列作分类）。
    """
    for ch in (charts or []):
        try:
            ctype = str(ch.get("type") or "bar").lower()
            title = str(ch.get("title") or "")
            anchor = str(ch.get("anchor") or "H2")
            data = ch.get("data")
            if ctype in ("line", "折线"):
                from openpyxl.chart import LineChart as _Chart, Reference
            elif ctype in ("pie", "饼"):
                from openpyxl.chart import PieChart as _Chart, Reference
            else:
                from openpyxl.chart import BarChart as _Chart, Reference
            chart = _Chart()
            chart.title = title

            if data and data.get("series"):
                cats = data.get("categories") or []
                start = ws.max_row + 2
                ws.cell(row=start, column=1, value=ch.get("category_title") or "类别")
                for j, s in enumerate(data["series"], start=2):
                    ws.cell(row=start, column=j, value=s.get("name") or f"系列{j-1}")
                for i, cval in enumerate(cats):
                    ws.cell(row=start + 1 + i, column=1, value=cval)
                    for j, s in enumerate(data["series"], start=2):
                        vals = s.get("values") or []
                        if i < len(vals):
                            ws.cell(row=start + 1 + i, column=j, value=vals[i])
                max_col = 1 + len(data["series"])
                d = Reference(ws, min_col=2, max_col=max_col, min_row=start, max_row=start + len(cats))
                chart.add_data(d, titles_from_data=True)
                cats_ref = Reference(ws, min_col=1, min_row=start + 1, max_row=start + len(cats))
                chart.set_categories(cats_ref)
            else:
                # 引用现有表格：需 ≥2 列、≥2 行（首行表头、首列分类）
                max_col, max_row = ws.max_column, ws.max_row
                if max_col < 2 or max_row < 2:
                    continue
                d = Reference(ws, min_col=2, max_col=max_col, min_row=1, max_row=max_row)
                chart.add_data(d, titles_from_data=True)
                cats_ref = Reference(ws, min_col=1, min_row=2, max_row=max_row)
                chart.set_categories(cats_ref)
            ws.add_chart(chart, anchor)
        except Exception:  # noqa: BLE001
            continue


def render_xlsx(content: str, rows: list | None = None, charts: list | None = None,
                sheet_name: str | None = None, sheets: list | None = None,
                options: dict | None = None) -> bytes:
    """多工作表 / 单表。

    sheets: [{name, rows, charts?, number_formats?, freeze?, header?}] —— 多表模式（优先）
    否则用单表 rows/content。
    options: {autosize(bool), header(bool)}
    """
    import openpyxl

    options = options or {}
    wb = openpyxl.Workbook()
    do_autosize = options.get("autosize", True)
    has_header = options.get("header", True)

    def _fill(ws, rws, chs, nfs=None, freeze=True, header=True):
        if rws:
            _xlsx_append_table(ws, rws, start_row=1, header=header, number_formats=nfs, freeze=freeze)
        _xlsx_add_charts(ws, chs)
        if do_autosize:
            _xlsx_autosize(ws)

    if sheets:
        wb.remove(wb.active)
        for sh in sheets:
            ws = wb.create_sheet(title=str(sh.get("name") or "Sheet")[:31])
            _fill(ws, sh.get("rows"), sh.get("charts"), sh.get("number_formats"),
                  sh.get("freeze", True), sh.get("header", True))
        if not wb.sheetnames:
            wb.create_sheet("Sheet1")
    else:
        ws = wb.active
        if sheet_name:
            ws.title = str(sheet_name)[:31]
        if rows:
            _fill(ws, rows, charts, (options or {}).get("number_formats"), True, has_header)
        else:
            parsed = []
            for ln in content.split("\n"):
                cells = ln.split(",") if "," in ln else ln.split("\t")
                parsed.append([c.strip() for c in cells])
            _fill(ws, parsed, charts, None, False, has_header)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==================== PDF ====================
_FONT_CACHE: dict[str, str] = {}

# 已知中文字体候选：(常规体名, 粗体名, 常规体路径, 粗体路径)
# 前置这些是为了在 Windows/macOS 上优先用系统自带的高质量字体。
_FONT_CANDS: list[tuple[str, str, str, str]] = [
    ("MicrosoftYaHei", "MicrosoftYaHei-Bold", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),
    ("SimSun", "SimHei", r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),
    ("PingFang", "PingFang-Bold", "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
]

# 精简镜像 / CI runner 常无预置路径：按目录扫描补齐。
# 只收 TrueType 轮廓（.ttf/.ttc）——reportlab 的 TTFont 不支持 CFF/OTF 轮廓，
# 因此 NotoSansCJK 的 .otf 变体刻意排除，WenQuanYi 等 TrueType 字体优先。
_FONT_SCAN_DIRS = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts/opentype",
)

# (字体名, 文件名 glob) —— 顺序即优先级
_FONT_SCAN_PATTERNS: list[tuple[str, str]] = [
    ("WenQuanYi", "wqy-zenhei.ttc"),
    ("WenQuanYiMicroHei", "wqy-microhei.ttc"),
    ("DroidSansFallback", "DroidSansFallbackFull.ttf"),
    ("NotoSansSC", "NotoSansSC-*.ttf"),
    ("NotoSansCJK", "NotoSansCJK-Regular.ttc"),
    ("SourceHanSansSC", "SourceHanSansSC-*.ttc"),
]


def _discover_cjk_fonts() -> list[tuple[str, str, str, str]]:
    """扫描系统字体目录，返回额外候选（应对 Docker slim / CI runner 无预置路径）。

    可用环境变量覆盖：RAG_PDF_FONT / RAG_PDF_FONT_BOLD 指向自带字体文件。
    """
    import glob
    import os

    cands: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    # 1) 显式环境变量（最高优先，便于离线/自托管字体）
    env_reg = os.environ.get("RAG_PDF_FONT", "").strip()
    env_bold = os.environ.get("RAG_PDF_FONT_BOLD", "").strip() or env_reg
    if env_reg and Path(env_reg).is_file():
        cands.append(("RagCustomFont", "RagCustomFont-Bold", env_reg, env_bold))
        seen.add("RagCustomFont")

    # 2) 目录扫描
    for name, pattern in _FONT_SCAN_PATTERNS:
        if name in seen:
            continue
        for d in _FONT_SCAN_DIRS:
            if not Path(d).is_dir():
                continue
            hits = sorted(glob.glob(str(Path(d) / "**" / pattern), recursive=True))
            if hits:
                cands.append((name, f"{name}-Bold", hits[0], hits[0]))
                seen.add(name)
                break
    return cands


def _pdf_register_fonts() -> tuple[str, str]:
    """注册中文字体 → (常规体, 粗体)。

    查找顺序：环境变量指定 → Windows/macOS 系统路径 → 系统目录扫描。
    全部落空才回退 Helvetica（此时中文会变乱码，故 Docker/CI 必须装中文字体）。
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if _FONT_CACHE.get("regular"):
        return _FONT_CACHE["regular"], _FONT_CACHE.get("bold") or _FONT_CACHE["regular"]

    for reg_name, bold_name, reg_path, bold_path in [*_discover_cjk_fonts(), *_FONT_CANDS]:
        try:
            if not Path(reg_path).is_file():
                continue
            if reg_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(reg_name, reg_path))
            bold = reg_name
            if bold_path != reg_path and Path(bold_path).is_file():
                if bold_name not in pdfmetrics.getRegisteredFontNames():
                    try:
                        pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                    except Exception:  # noqa: BLE001
                        pass
                if bold_name in pdfmetrics.getRegisteredFontNames():
                    bold = bold_name
            pdfmetrics.registerFontFamily(reg_name, normal=reg_name, bold=bold, italic=reg_name, boldItalic=bold)
            _FONT_CACHE["regular"] = reg_name
            _FONT_CACHE["bold"] = bold
            return reg_name, bold
        except Exception:  # noqa: BLE001
            continue
    # 全部落空：中文会渲染成乱码（reportlab 用 Helvetica 画 CJK 得到的是占位符）。
    # 显式告警而不静默，避免此类问题在容器里悄悄产出乱码 PDF。
    logging.getLogger(__name__).warning(
        "pdf_cjk_font_missing: 未找到可用中文字体，PDF 中文将显示为乱码。"
        "修复：apt-get install -y fonts-wqy-zenhei（Docker/CI），"
        "或用 RAG_PDF_FONT 指向自带字体文件。"
    )
    _FONT_CACHE["regular"] = _FONT_CACHE["bold"] = "Helvetica"
    return "Helvetica", "Helvetica"


def _pdf_inline_md(text: str) -> str:
    """转义 XML 并转换少量行内 markdown（**粗体**、`code`）。"""
    s = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<font face='Courier'>\1</font>", s)
    return s


def _pdf_make_doc(buf, font: str, bold: str, on_page):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=64, rightMargin=64,
                          topMargin=70, bottomMargin=64,
                          title="", author="")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])
    return doc


def _pdf_make_onpage(font: str, bold: str, meta: dict):
    """返回 onPage 回调：画页眉细线+文字、页脚细线+页码。"""
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    header = str(meta.get("header") or "")
    footer = str(meta.get("footer") or "")
    hide_first = bool(meta.get("cover"))

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = canvas._pagesize
        number = canvas.getPageNumber()
        if not (hide_first and number == 1):
            # 页眉
            if header:
                canvas.setFont(font, 8.5)
                canvas.setFillColor(colors.HexColor("#94A3B8"))
                canvas.drawString(doc.leftMargin, h - 46, header)
                canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
                canvas.setLineWidth(0.5)
                canvas.line(doc.leftMargin, h - 52, w - doc.rightMargin, h - 52)
            # 页脚：页码（居中）+ 可选页脚文字
            canvas.setFont(font, 8.5)
            canvas.setFillColor(colors.HexColor("#94A3B8"))
            canvas.drawCentredString(w / 2, 40, f"第 {number} 页")
            if footer:
                canvas.drawString(doc.leftMargin, 40, footer)
            canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
            canvas.setLineWidth(0.5)
            canvas.line(doc.leftMargin, 52, w - doc.rightMargin, 52)
        canvas.restoreState()

    return on_page


def _pdf_cover(flow, meta: dict, font: str, bold: str) -> None:
    """向 flow 追加封面（末页分页）。"""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle

    flow.append(Spacer(1, 90 * mm))
    title_style = ParagraphStyle("cov_title", fontName=bold, fontSize=30, leading=40,
                                 alignment=1, textColor=colors.HexColor("#1E3A8A"))
    flow.append(Paragraph(_pdf_inline_md(str(meta.get("title") or "")), title_style))
    if meta.get("subtitle"):
        flow.append(Spacer(1, 8 * mm))
        flow.append(Paragraph(_pdf_inline_md(str(meta["subtitle"])),
                              ParagraphStyle("cov_sub", fontName=font, fontSize=15, leading=22,
                                             alignment=1, textColor=colors.HexColor("#64748B"))))
    flow.append(Spacer(1, 70 * mm))
    for line in (meta.get("author"), meta.get("date")):
        if line:
            flow.append(Paragraph(_pdf_inline_md(str(line)),
                                  ParagraphStyle("cov_meta", fontName=font, fontSize=11, leading=18,
                                                 alignment=1, textColor=colors.HexColor("#94A3B8"))))
    flow.append(PageBreak())


def render_pdf(content: str, meta: dict | None = None) -> bytes:
    """专业排版 PDF：封面 / 页眉 / 页码 / 标题层级 / 表格样式（自动分页、跨页表头重复）。"""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

    meta = meta or {}
    font, bold = _pdf_register_fonts()
    buf = io.BytesIO()
    doc = _pdf_make_doc(buf, font, bold, _pdf_make_onpage(font, bold, meta))
    doc.title = str(meta.get("title") or "")
    doc.author = str(meta.get("author") or "")

    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Heading1"], fontName=bold, fontSize=19, leading=26,
                        spaceBefore=10, spaceAfter=8, textColor=colors.HexColor("#1E3A8A"))
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontName=bold, fontSize=15, leading=21,
                        spaceBefore=8, spaceAfter=6, textColor=colors.HexColor("#1E3A8A"))
    h3 = ParagraphStyle("h3", parent=base["Heading3"], fontName=bold, fontSize=12.5, leading=18,
                        spaceBefore=6, spaceAfter=4, textColor=colors.HexColor("#334155"))
    h4 = ParagraphStyle("h4", parent=base["Heading3"], fontName=bold, fontSize=11, leading=16,
                        spaceBefore=4, spaceAfter=3, textColor=colors.HexColor("#334155"))
    body = ParagraphStyle("body", parent=base["BodyText"], fontName=font, fontSize=10.5, leading=17,
                          spaceAfter=5, textColor=colors.HexColor("#1F2937"))
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=4, spaceAfter=3)
    num = ParagraphStyle("num", parent=body, leftIndent=14, spaceAfter=3)
    quote = ParagraphStyle("quote", parent=body, fontName=font, fontSize=10.5, leading=17,
                           leftIndent=14, textColor=colors.HexColor("#475569"))

    flow: list = []
    if meta.get("cover"):
        _pdf_cover(flow, meta, font, bold)
    elif meta.get("title"):
        flow.append(Paragraph(_pdf_inline_md(str(meta["title"])), h1))

    def _table(header, body_rows):
        ncol = max([len(header)] + [len(r) for r in body_rows]) if body_rows else len(header)
        data = [[Paragraph(_pdf_inline_md(str(header[i])) if i < len(header) else "",
                           ParagraphStyle("th", fontName=bold, fontSize=9.5, leading=13,
                                          textColor=colors.white))
                 for i in range(ncol)]]
        for ri, r in enumerate(body_rows):
            data.append([Paragraph(_pdf_inline_md(str(r[i])) if i < len(r) else "",
                                   ParagraphStyle("td", fontName=font, fontSize=9.5, leading=13,
                                                  textColor=colors.HexColor("#1F2937")))
                         for i in range(ncol)])
        t = Table(data, hAlign="LEFT", repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]
        for ri in range(1, len(data)):
            if ri % 2 == 0:
                style.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#F1F5F9")))
        t.setStyle(TableStyle(style))
        return t

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
                flow.append(_table(parsed[0], parsed[1]))
                flow.append(Spacer(1, 8))
            i = j
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            flow.append(Paragraph(_pdf_inline_md(m.group(2)),
                                  {1: h1, 2: h2, 3: h3, 4: h4}[lvl]))
        elif s.startswith("- ") or s.startswith("* "):
            flow.append(Paragraph(_pdf_inline_md(s[2:]), bullet, bulletText="•"))
        elif re.match(r"^\d+\.\s", s):
            flow.append(Paragraph(_pdf_inline_md(re.sub(r"^\d+\.\s", "", s)), num))
        elif s.startswith("> "):
            flow.append(Paragraph(_pdf_inline_md(s[2:]), quote))
        elif s.strip() == "---":
            flow.append(Spacer(1, 6))
            flow.append(Table([[""]], colWidths=[doc.width], rowHeights=[0.5],
                              style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5,
                                                 colors.HexColor("#E2E8F0"))])))
            flow.append(Spacer(1, 6))
        elif not s.strip():
            flow.append(Spacer(1, 6))
        else:
            flow.append(Paragraph(_pdf_inline_md(s), body))
        i += 1

    doc.build(flow or [Paragraph("", body)])
    return buf.getvalue()
