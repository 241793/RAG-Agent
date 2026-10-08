"""答案-引用一致性校验（防幻觉）：检测答案里是否有超出实际引用范围的 [n]。"""
from __future__ import annotations

import re

_CITE_RE = re.compile(r"\[(\d+)\]")


def check(answer: str, citations: list) -> dict:
    """返回 {used_ids, max_id, has_fake_cite, ok}。

    has_fake_cite：答案引用了超出 citations 数量的编号（或无可引用却带编号）→ 疑似编造引用。
    仅用于标记/前端提示，不做硬拦截、不自动改写。
    """
    used = sorted({int(m) for m in _CITE_RE.findall(answer or "")})
    n = len(citations or [])
    max_id = used[-1] if used else 0
    has_fake = bool(used) and (n == 0 or max_id > n)
    return {
        "used_ids": used,
        "max_id": max_id,
        "citation_count": n,
        "has_fake_cite": has_fake,
        "ok": not has_fake,
    }
