"""办公文档生成工具：会议纪要 / 周报日报 / 待办清单 / 公文。

在 generate_file 之上提供**结构化模板**：LLM 只需按字段填内容，工具负责排版成
规整的 Markdown（含表格），再渲染为 docx/pdf/xlsx/md。产物登记为 Artifact 供下载。

设计：模板用「标题 + 章节/表格」的固定骨架，避免每次排版不一致；内容由 AI 填充。
"""
from __future__ import annotations

from app.agents.tools.base import ToolContext, ToolResult, WriteToolMixin
from app.agents.tools.file_tools import _render, _save_artifact


def _md_table(headers: list[str], rows: list[list]) -> str:
    if not headers:
        return ""
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        cells = [str(r[i]) if i < len(r) else "" for i in range(len(headers))]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _fmt_minutes(d: dict) -> str:
    """会议纪要模板。"""
    lines = [f"# {d.get('title') or '会议纪要'}", ""]
    meta = []
    if d.get("date"):
        meta.append(f"**日期**：{d['date']}")
    if d.get("time"):
        meta.append(f"**时间**：{d['time']}")
    if d.get("location"):
        meta.append(f"**地点**：{d['location']}")
    if d.get("host"):
        meta.append(f"**主持人**：{d['host']}")
    if meta:
        lines.append("　".join(meta)); lines.append("")
    if d.get("attendees"):
        lines.append(f"**参会人员**：{', '.join(d['attendees'])}"); lines.append("")
    if d.get("agenda"):
        lines.append("## 议题"); lines.append("")
        for i, a in enumerate(d["agenda"], 1):
            lines.append(f"{i}. {a}")
        lines.append("")
    if d.get("discussion"):
        lines.append("## 讨论要点"); lines.append("")
        lines.append(str(d["discussion"])); lines.append("")
    if d.get("decisions"):
        lines.append("## 决议事项"); lines.append("")
        for x in d["decisions"]:
            lines.append(f"- {x}")
        lines.append("")
    if d.get("todos"):
        lines.append("## 待办事项"); lines.append("")
        rows = [[t.get("task", ""), t.get("owner", ""), t.get("due", "")] for t in d["todos"]]
        lines.append(_md_table(["事项", "负责人", "截止时间"], rows)); lines.append("")
    return "\n".join(lines)


def _fmt_report(d: dict) -> str:
    """周报/日报模板。"""
    kind = d.get("kind") or "周报"
    lines = [f"# {d.get('title') or kind}", ""]
    meta = []
    if d.get("author"):
        meta.append(f"**汇报人**：{d['author']}")
    if d.get("period"):
        meta.append(f"**周期**：{d['period']}")
    if meta:
        lines.append("　".join(meta)); lines.append("")
    if d.get("summary"):
        lines.append("## 工作概述"); lines.append(""); lines.append(str(d["summary"])); lines.append("")
    if d.get("done"):
        lines.append("## 已完成"); lines.append("")
        for x in d["done"]:
            lines.append(f"- {x}")
        lines.append("")
    if d.get("doing"):
        lines.append("## 进行中"); lines.append("")
        rows = [[t.get("task", ""), t.get("progress", ""), t.get("owner", "")] for t in d["doing"]]
        lines.append(_md_table(["事项", "进度", "负责人"], rows)); lines.append("")
    if d.get("plan"):
        lines.append("## 下阶段计划"); lines.append("")
        for x in d["plan"]:
            lines.append(f"- {x}")
        lines.append("")
    if d.get("issues"):
        lines.append("## 问题与风险"); lines.append("")
        for x in d["issues"]:
            lines.append(f"- {x}")
        lines.append("")
    return "\n".join(lines)


def _fmt_todo(d: dict) -> str:
    """待办清单模板。"""
    lines = [f"# {d.get('title') or '待办清单'}", ""]
    if d.get("context"):
        lines.append(str(d["context"])); lines.append("")
    items = d.get("items") or []
    if items:
        rows = [[
            ("☑" if t.get("done") else "☐"), t.get("task", ""),
            t.get("owner", ""), t.get("priority", ""), t.get("due", ""),
        ] for t in items]
        lines.append(_md_table(["完成", "事项", "负责人", "优先级", "截止"], rows))
    return "\n".join(lines)


def _fmt_official(d: dict) -> str:
    """公文/通知模板。"""
    lines = [f"# {d.get('title') or '通知'}", ""]
    if d.get("to"):
        lines.append(f"**致**：{d['to']}"); lines.append("")
    if d.get("from"):
        lines.append(f"**发文单位**：{d['from']}"); lines.append("")
    if d.get("date"):
        lines.append(f"**日期**：{d['date']}"); lines.append("")
    lines.append("")
    if d.get("body"):
        lines.append(str(d["body"])); lines.append("")
    if d.get("sections"):
        for sec in d["sections"]:
            if sec.get("heading"):
                lines.append(f"## {sec['heading']}")
            lines.append(str(sec.get("content", ""))); lines.append("")
    if d.get("signature"):
        lines.append(""); lines.append(f"> {d['signature']}")
    return "\n".join(lines)


_TEMPLATES = {
    "minutes": ("会议纪要", _fmt_minutes),
    "report": ("周报/日报", _fmt_report),
    "todo": ("待办清单", _fmt_todo),
    "official": ("公文/通知", _fmt_official),
}


class OfficeDocTool(WriteToolMixin):
    name = "generate_office_doc"
    description = (
        "生成规整的办公文档（会议纪要/周报日报/待办清单/公文通知），排版规范、支持表格，"
        "导出为 docx/pdf/xlsx/md。比 generate_file 更适合正式文档：你只需按字段填内容，工具负责排版。\n"
        "template=minutes 参数：title/date/time/location/host/attendees[]/agenda[]/discussion/"
        "decisions[]/todos[{task,owner,due}]；\n"
        "template=report 参数：kind(周报|日报)/title/author/period/summary/done[]/"
        "doing[{task,progress,owner}]/plan[]/issues[]；\n"
        "template=todo 参数：title/context/items[{task,owner,priority,due,done}]；\n"
        "template=official 参数：title/to/from/date/body/sections[{heading,content}]/signature。"
    )
    required_permission = "file:write"
    kind = "write"
    parameters = {
        "type": "object",
        "properties": {
            "template": {"type": "string", "enum": list(_TEMPLATES.keys()),
                         "description": "minutes=会议纪要, report=周报日报, todo=待办, official=公文"},
            "format": {"type": "string", "enum": ["docx", "pdf", "xlsx", "md"], "default": "docx"},
            "filename": {"type": "string", "description": "文件名（可省略扩展名）"},
            "data": {"type": "object", "description": "按模板填写的字段（见描述）"},
        },
        "required": ["template", "data"],
    }

    def summarize(self, args: dict) -> str:
        tpl = _TEMPLATES.get(str(args.get("template")), ("文档", None))[0]
        title = (args.get("data") or {}).get("title") or tpl
        return f"生成{tpl}「{title}」（{args.get('format') or 'docx'}）"

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        tpl = str(args.get("template") or "")
        if tpl not in _TEMPLATES:
            return ToolResult(content=f"不支持的模板：{tpl}", is_error=True)
        label, fn = _TEMPLATES[tpl]
        data = args.get("data") or {}
        if not isinstance(data, dict):
            return ToolResult(content="data 需为对象", is_error=True)
        try:
            md = fn(data)
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"排版失败：{str(e)[:200]}", is_error=True)

        fmt = str(args.get("format") or "docx").lower()
        if fmt not in ("docx", "pdf", "xlsx", "md"):
            fmt = "docx"
        title = str(data.get("title") or label)
        safe_title = "".join(ch for ch in title if ch not in '\\/:*?"<>|')[:60]
        filename = str(args.get("filename") or f"{safe_title}.{fmt}")
        if not filename.lower().endswith(f".{fmt}"):
            filename = f"{filename}.{fmt}"
        try:
            if fmt == "md":
                blob, mime = md.encode("utf-8"), "text/markdown"
            else:
                blob, mime = _render({"format": fmt, "content": md})
        except Exception as e:  # noqa: BLE001
            return ToolResult(content=f"生成失败：{str(e)[:200]}", is_error=True)
        file_key, art, _ = _save_artifact(ctx, filename, blob, mime)
        await ctx.db.flush()
        return ToolResult(
            content=f"已生成{label}「{filename}」（{len(blob)} 字节，可下载）",
            data={"file_key": file_key, "artifact_id": art.id, "name": filename, "mime": mime,
                  "size": len(blob), "url": f"/api/v1/chat/attachments/{file_key}"},
        )


OFFICE_TOOLS = [OfficeDocTool()]
