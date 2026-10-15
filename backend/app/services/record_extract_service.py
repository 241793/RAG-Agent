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
    """构造抽取用的 (system, user) 提示词。

    **实测教训（勿回退）**：字段定义与输出示例必须放进 **user** 消息，不能只放 system。
    部分模型（如 deepseek 系列）对 system 指令遵从度差：单独给 system 时会把 key 写成
    中文标签（{"客户":"张三"}）或输出 Markdown 列表，导致按英文字段名过滤后全为 null。
    把「字段定义 + 一条输出示例 + 待抽取文本」都放进 user，实测稳定返回正确 JSON。
    """
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

    names = [f.get("name") for f in fields if f.get("name")]
    # 一条贴合模板的输出示例：key 用英文字段名、值用占位符
    example_obj = {n: _example_for(f) for n, f in zip(names, fields)} if names else {"field": "值"}
    example = json.dumps(example_obj, ensure_ascii=False)

    system = "你是数据录入助手，只输出 JSON，不要任何解释或 Markdown 代码块。"
    user = (
        "请从下面的文本中抽取信息，严格按给定字段输出 JSON。\n"
        "规则：\n"
        "1. 只输出 JSON，禁止任何解释文字、禁止 markdown 代码块。\n"
        "2. key 必须用下面的英文名（**不要用中文标签**）；找不到的值填 null，不要编造。\n"
        "3. 若文本含多条记录，输出 JSON 数组；否则输出单个 JSON 对象。\n"
        "4. 日期统一 YYYY-MM-DD，金额只保留数字。\n"
    )
    if template.instructions:
        user += f"\n业务背景：{template.instructions}\n"
    user += f"\n字段定义（key 用英文名）：\n{field_desc}\n"
    user += f"\n输出示例（严格照此格式）：{example}\n"
    user += f"\n待抽取文本：\n{text}\n\n直接输出 JSON："
    return system, user


def _example_for(f: dict) -> object:
    """按字段类型给一个示例占位值，帮助模型对齐格式。"""
    typ = f.get("type") or "text"
    opts = f.get("options")
    if opts:
        return opts[0]
    return {"number": 0, "date": "2026-01-01", "phone": "13800000000"}.get(typ, "示例")


async def extract_records(
    db: AsyncSession, *, tenant_id: int, template, text: str
) -> list[dict]:
    """调用 LLM 抽取，返回记录列表（每项是字段→值）。

    容错：模型可能把 key 写成中文标签/大小写不一致/带空格，这里统一归一到模板的
    英文字段名；若首次返回全空（模型没抽到），用更硬的提示重试一次。
    """
    from app.providers.base import ChatMessage
    from app.providers.registry import get_llm

    system, user = build_prompt(template, text)
    llm, rm = await get_llm(db, tenant_id=tenant_id)

    async def _call(u: str) -> list[dict]:
        res = await llm.chat(
            [ChatMessage(role="system", content=system), ChatMessage(role="user", content=u)],
            model=rm.model_name, stream=False,
        )
        parsed = _extract_json(getattr(res, "content", "") or "")
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            records = [parsed]
        elif isinstance(parsed, list):
            records = [r for r in parsed if isinstance(r, dict)]
        else:
            return []
        return _normalize_records(records, template)

    out = await _call(user)
    # 首次全空（含解析失败）→ 重试一次，措辞更硬，抑制解释性文字
    if not out or all(all(v is None for v in r.values()) for r in out):
        retry_user = (user + "\n\n注意：上一次没有给出结果。请**只输出一行 JSON**，"
                      "key 用英文字段名，值为从文本抽取的内容；不要任何解释。")
        retry = await _call(retry_user)
        if retry and not all(all(v is None for v in r.values()) for r in retry):
            out = retry
    if not out:
        raise ValueError("AI 未能返回可解析的 JSON，请检查文本或稍后重试")
    return out


def _norm_key(s: str) -> str:
    """归一化 key：去空白、转小写、去常见分隔符，用于宽松匹配。"""
    return re.sub(r"[\s_\-]+", "", str(s or "").strip().lower())


def _normalize_records(records: list[dict], template) -> list[dict]:
    """把模型输出对齐到模板字段：key 归一（中文label/大小写/空格 → 英文字段名）+ 按类型归一值。"""
    fields = template.fields or []
    names = [f.get("name") for f in fields if f.get("name")]
    types = {f.get("name"): (f.get("type") or "text") for f in fields if f.get("name")}
    # 建立「可接受 key 的归一形式 → 英文字段名」映射：英文名本身 + label
    accept: dict[str, str] = {}
    for f in fields:
        n = f.get("name")
        if not n:
            continue
        accept[_norm_key(n)] = n
        if f.get("label"):
            accept[_norm_key(f["label"])] = n

    out: list[dict] = []
    for r in records:
        row: dict = {n: None for n in names}
        extra: dict = {}  # 归一对不上的 key 也保留（避免丢信息）
        for k, v in r.items():
            target = accept.get(_norm_key(k))
            if target:
                row[target] = v
            elif _norm_key(k) in {_norm_key(x) for x in names}:
                row[next(x for x in names if _norm_key(x) == _norm_key(k))] = v
            else:
                extra[str(k)] = v
        for k, v in list(row.items()):
            row[k] = _normalize(types.get(k, "text"), v)
        if extra:
            # 模板字段之后追加额外字段，便于人工核对
            dup = {n for n in names}
            for k, v in extra.items():
                if k not in dup:
                    row[k] = v
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
