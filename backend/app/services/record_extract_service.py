"""智能录单服务：用 LLM 从文本中按模板抽取结构化字段。

设计要点：
- 模板字段 + 业务提示 → 组 prompt → 要求 LLM 返回 JSON（对象或数组）
- 容错解析：从可能带 ```json 包裹或前后杂质的回复中提取 JSON
- 一条文本可能含多单（返回数组），也可能单条（返回对象→包成数组）
"""
from __future__ import annotations

import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("record_extract")


def _extract_json(text: str) -> object | None:
    """从 LLM 回复中提取 JSON（去掉 ```json 包裹与前后杂质）。"""
    if not text:
        return None
    s = text.strip()
    # 去代码块围栏
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 退一步：找第一个 { 或 [ 到最后一个 } 或 ]
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = s.find(opener), s.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


def build_prompt(template, text: str) -> tuple[str, str]:
    """构造抽取用的 (system, user) 提示词。"""
    fields = template.fields or []
    lines = []
    for f in fields:
        name = f.get("name")
        label = f.get("label") or name
        typ = f.get("type") or "text"
        req = "必填" if f.get("required") else "可选"
        desc = f.get("desc") or ""
        opts = f.get("options")
        extra = f"（可选值：{', '.join(map(str, opts))}）" if opts else ""
        lines.append(f"- {name}（{label}，{typ}，{req}）{desc}{extra}")
    field_desc = "\n".join(lines) or "- 无字段定义"

    system = (
        "你是数据录入助手。请从用户提供的文本中抽取信息，严格按给定字段输出 JSON。\n"
        "规则：\n"
        "1. 只输出 JSON，不要任何解释文字。\n"
        "2. 若文本包含多条记录，输出 JSON 数组；否则输出单个 JSON 对象。\n"
        "3. 字段名必须用英文 key（见下）；找不到的值填 null，不要编造。\n"
        "4. 日期统一为 YYYY-MM-DD，金额只保留数字。\n"
    )
    if template.instructions:
        system += f"\n业务背景：{template.instructions}\n"
    system += f"\n字段定义：\n{field_desc}\n"
    user = f"请从以下文本中抽取上述字段：\n\n{text}"
    return system, user


async def extract_records(
    db: AsyncSession, *, tenant_id: int, template, text: str
) -> list[dict]:
    """调用 LLM 抽取，返回记录列表（每项是字段→值）。"""
    from app.providers.base import ChatMessage
    from app.providers.registry import get_llm

    system, user = build_prompt(template, text)
    llm, rm = await get_llm(db, tenant_id=tenant_id)
    res = await llm.chat(
        [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
        model=rm.model_name, stream=False,
    )
    parsed = _extract_json(getattr(res, "content", "") or "")
    if parsed is None:
        raise ValueError("AI 未能返回可解析的 JSON，请检查文本或稍后重试")
    if isinstance(parsed, dict):
        records = [parsed]
    elif isinstance(parsed, list):
        records = [r for r in parsed if isinstance(r, dict)]
    else:
        raise ValueError("AI 返回的 JSON 结构不是对象或数组")
    # 用模板字段名过滤/补全（保留模板定义的 key 顺序，缺的补 null）
    fields = template.fields or []
    names = [f.get("name") for f in fields if f.get("name")]
    types = {f.get("name"): (f.get("type") or "text") for f in fields if f.get("name")}
    out: list[dict] = []
    for r in records:
        row = {n: r.get(n) for n in names} if names else dict(r)
        for k, v in list(row.items()):
            row[k] = _normalize(types.get(k, "text"), v)
        out.append(row)
    return out


def _normalize(typ: str, v):
    """按字段类型归一化取值（宽松：失败则原样保留，不丢信息）。"""
    if v is None or v == "":
        return None
    import re as _re

    if typ == "number":
        if isinstance(v, (int, float)):
            return v
        m = _re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
        if m:
            num = float(m.group())
            return int(num) if num.is_integer() else num
        return v
    if typ == "date":
        if isinstance(v, str):
            m = _re.match(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", v.strip())
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return v
    if typ == "phone":
        digits = _re.sub(r"\D", "", str(v))
        return digits or v
    return v
