"""PPTX 生成器：用 python-pptx 自绘版式（不依赖模板文件），产出有设计感的幻灯片。

支持版式（slide.layout）：
- cover    封面：整页主题色背景 + 大标题 + 副标题 + 底部信息
- section  章节：主题色底 + 巨大编号 + 章节标题
- bullets  要点（默认）：顶部色条 + 标题 + 分层要点
- two-col  两栏：标题 + 左右两栏要点
- quote    引用：放大引言 + 出处
- table    表格：标题 + 数据表
- end      结尾：主题色底 + 结束语

主题（theme）：传主题色 hex（如 "#2563eb"）或用内置名 blue/green/dark/red/orange/purple/teal。
"""
from __future__ import annotations

import io

# 内置主题：主色 + 深色变体（用于背景/强调）
_THEMES = {
    "blue": ("2563EB", "1E3A8A"),
    "green": ("10B981", "065F46"),
    "dark": ("334155", "0F172A"),
    "red": ("DC2626", "7F1D1D"),
    "orange": ("EA580C", "7C2D12"),
    "purple": ("7C3AED", "4C1D95"),
    "teal": ("0D9488", "134E4A"),
}

_W, _H = 12192000, 6858000  # 16:9（EMU）


def _norm_color(c) -> tuple[str, str]:
    """返回 (主色, 深色). 支持内置名 / #RRGGBB / RRGGBB。"""
    if isinstance(c, str) and c.lower().lstrip("#") in _THEMES:
        return _THEMES[c.lower().lstrip("#")]
    if isinstance(c, str) and c.startswith("#") and len(c) == 7:
        main = c[1:].upper()
        return main, _DARKEN(main)
    if isinstance(c, str) and len(c) == 6:
        return c.upper(), _DARKEN(c.upper())
    return _THEMES["blue"]


def _rgb(hex6: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(hex6)


def _DARKEN(hex6: str, factor: float = 0.55) -> str:
    try:
        r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
        return "".join(f"{max(0, int(v * factor)):02X}" for v in (r, g, b))
    except Exception:  # noqa: BLE001
        return "1E3A8A"


def _set_bg(slide, hex6: str) -> None:
    """整页纯色背景（用一个铺满的矩形实现，兼容各主题）。"""
    from pptx.util import Emu

    shp = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(_W), Emu(_H))  # 1=矩形
    shp.fill.solid()
    shp.fill.fore_color.rgb = _rgb(hex6)
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _add_text(slide, left, top, width, height, text, *, size, bold=False, color="000000",
              align="left", font="Microsoft YaHei", anchor="top", line_spacing=None):
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Pt

    tb = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(width), Emu(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}[anchor]
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
    if line_spacing:
        p.line_spacing = line_spacing
    r = p.add_run()
    r.text = str(text)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.name = font
    r.font.color.rgb = _rgb(color)
    return tb


def _bullets_frame(slide, left, top, width, height, bullets, *, color="334155", size=18,
                   bullet_color=None, font="Microsoft YaHei"):
    """要点列表：支持字符串或 {text, level} / 嵌套 dict。"""
    from pptx.util import Emu, Pt
    from pptx.oxml.ns import qn

    tb = slide.shapes.add_textbox(Emu(left), Emu(top), Emu(width), Emu(height))
    tf = tb.text_frame
    tf.word_wrap = True
    bc = _rgb(bullet_color or "2563EB")
    for i, b in enumerate(bullets or []):
        if isinstance(b, dict):
            text = str(b.get("text") or b.get("title") or "")
            level = int(b.get("level") or 0)
        else:
            text = str(b)
            level = 0
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = min(level, 4)
        p.space_after = Pt(6)
        # 项目符号
        pPr = p._p.get_or_add_pPr()
        buChar = pPr.makeelement(qn("a:buChar"), {"char": "•" if level == 0 else "–"})
        buClr = pPr.makeelement(qn("a:buClr"), {})
        srgb = pPr.makeelement(qn("a:srgbClr"), {"val": (bullet_color or "2563EB")})
        buClr.append(srgb)
        pPr.append(buClr)
        pPr.append(buChar)
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size - level * 2)
        r.font.name = font
        r.font.color.rgb = _rgb(color if level == 0 else "64748B")
    _ = bc
    return tb


def _render(slides: list, theme) -> bytes:
    from pptx import Presentation
    from pptx.util import Emu

    main, dark = _norm_color(theme)
    prs = Presentation()
    prs.slide_width = Emu(_W)
    prs.slide_height = Emu(_H)
    blank = prs.slide_layouts[6]  # 空白版式

    for idx, s in enumerate(slides or []):
        if not isinstance(s, dict):
            s = {"title": str(s), "bullets": []}
        layout = str(s.get("layout") or s.get("type") or "bullets").lower()
        slide = prs.slides.add_slide(blank)

        if layout == "cover":
            _set_bg(slide, main)
            # 装饰条
            _add_text(slide, 838200, 2100000, _W - 1676400, 1400000,
                      s.get("title") or "", size=44, bold=True, color="FFFFFF")
            sub = s.get("subtitle") or s.get("desc") or ""
            if sub:
                _add_text(slide, 850000, 3400000, _W - 1700000, 900000, sub, size=20, color="E2E8F0")
            foot = s.get("footer") or s.get("author") or ""
            if foot:
                _add_text(slide, 850000, 5600000, _W - 1700000, 500000, foot, size=14, color="CBD5E1")
            else:
                _add_text(slide, 850000, 5600000, _W - 1700000, 500000, "企业 AI 中台", size=13, color="CBD5E1")

        elif layout == "section":
            _set_bg(slide, dark)
            num = s.get("number") or (idx + 1)
            _add_text(slide, 838200, 2300000, 2000000, 1500000, f"{num:02d}", size=96, bold=True, color="94A3B8")
            _add_text(slide, 2500000, 2650000, _W - 3300000, 1200000, s.get("title") or "", size=36, bold=True, color="FFFFFF")

        elif layout == "end":
            _set_bg(slide, main)
            _add_text(slide, 0, 2800000, _W, 1000000, s.get("title") or "谢谢", size=44, bold=True, color="FFFFFF", align="center")
            if s.get("subtitle") or s.get("desc"):
                _add_text(slide, 0, 3900000, _W, 700000, s.get("subtitle") or s.get("desc"), size=18, color="E2E8F0", align="center")

        elif layout == "quote":
            _set_bg(slide, "F8FAFC")
            _add_text(slide, 1000000, 2400000, _W - 2000000, 1600000,
                      f"“{s.get('title') or s.get('quote') or ''}”", size=30, color=dark)
            src = s.get("subtitle") or s.get("source") or ""
            if src:
                _add_text(slide, 1000000, 4200000, _W - 2000000, 600000, f"— {src}", size=16, color="64748B")

        elif layout == "two-col":
            _render_head(slide, s.get("title") or "", main)
            colw = (_W - 838200 * 2 - 300000) // 2
            left_items = s.get("left") or (s.get("bullets") or [])[:len(s.get("bullets") or []) // 2]
            right_items = s.get("right") or (s.get("bullets") or [])[len(s.get("bullets") or []) // 2:]
            _bullets_frame(slide, 838200, 1900000, colw, _H - 2400000, left_items, size=17, bullet_color=main)
            _bullets_frame(slide, 838200 + colw + 300000, 1900000, colw, _H - 2400000, right_items, size=17, bullet_color=main)

        elif layout == "table":
            _render_head(slide, s.get("title") or "", main)
            data = s.get("rows") or s.get("data") or []
            if data:
                cols = len(data[0]) if data else 0
                rows = len(data)
                gt = slide.shapes.add_table(rows, cols, Emu(838200), Emu(1900000),
                                            Emu(_W - 1676400), Emu(min(_H - 2400000, 500000 + rows * 400000))).table
                for ri, row in enumerate(data):
                    for ci, cell in enumerate(row):
                        if ci >= cols:
                            continue
                        c = gt.cell(ri, ci)
                        c.text = str(cell)
                        for para in c.text_frame.paragraphs:
                            for run in para.runs:
                                run.font.size = __import__("pptx.util", fromlist=["Pt"]).Pt(14)
                                run.font.name = "Microsoft YaHei"
                                run.font.color.rgb = _rgb("0F172A" if ri else "FFFFFF")
                        if ri == 0:
                            c.fill.solid(); c.fill.fore_color.rgb = _rgb(main)

        else:  # bullets（默认）
            _render_head(slide, s.get("title") or "", main)
            _bullets_frame(slide, 838200, 1900000, _W - 1676400, _H - 2400000,
                           s.get("bullets") or [], size=18, bullet_color=main)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _render_head(slide, title: str, main: str) -> None:
    """内容页顶部：左侧主题色竖条 + 标题 + 底部细分隔线。"""
    from pptx.util import Emu

    bar = slide.shapes.add_shape(1, Emu(838200), Emu(760000), Emu(90000), Emu(760000))
    bar.fill.solid(); bar.fill.fore_color.rgb = _rgb(main); bar.line.fill.background(); bar.shadow.inherit = False
    _add_text(slide, 1030000, 720000, _W - 2000000, 900000, title, size=28, bold=True, color="0F172A")
    line = slide.shapes.add_shape(1, Emu(838200), Emu(1680000), Emu(_W - 1676400), Emu(18000))
    line.fill.solid(); line.fill.fore_color.rgb = _rgb("E2E8F0"); line.line.fill.background(); line.shadow.inherit = False


def render_pptx(content: str = "", slides: list | None = None, theme=None) -> bytes:
    """对外入口。slides 为空时把 content 按空行分块，转成 [{title,bullets}]。"""
    if not slides:
        slides = []
        for block in (content or "").split("\n\n"):
            lines = [x for x in block.split("\n") if x.strip()]
            if not lines:
                continue
            slides.append({
                "title": lines[0].lstrip("# ").strip(),
                "bullets": [ln.lstrip("-*# ").strip() for ln in lines[1:]],
            })
    return _render(slides, theme)
