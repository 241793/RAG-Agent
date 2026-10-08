"""Token 粗略估算（零依赖）。用于上下文阈值判断，非精确计数。"""
from __future__ import annotations

import re

_CJK_RE = re.compile(r"[一-鿿　-〿＀-￯]")


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中日韩字符约 len/1.5，其余（英数符号）约 len/4。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


def estimate_messages(msgs: list) -> int:
    """估算一批消息的总 token（支持 ChatMessage 对象或 dict）。"""
    total = 0
    for m in msgs:
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content", "")
        total += estimate_tokens(content or "") + 4  # 每条消息的角色/格式开销
    return total
