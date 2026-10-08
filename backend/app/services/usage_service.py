"""用量归一化：抹平各 LLM 驱动的 usage 形状差异。

统一契约（前端只认这 4 个键）：
  {prompt_tokens, completion_tokens, total_tokens, cached_tokens}
"""
from __future__ import annotations


def normalize_usage(raw: dict | None) -> dict:
    """把驱动返回的 usage 归一为统一契约。

    - OpenAI 兼容：有 prompt_tokens/completion_tokens，total 可能缺，
      缓存命中在 prompt_tokens_details.cached_tokens。
    - Anthropi：可能给 input_tokens/output_tokens；流式只有 completion。
    - total_tokens 不保证存在 → 用 prompt+completion 兜底。
    """
    raw = raw or {}
    p = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
    c = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
    total = int(raw.get("total_tokens") or (p + c))
    details = raw.get("prompt_tokens_details") or {}
    cached = int(raw.get("cached_tokens") or details.get("cached_tokens") or 0)
    return {
        "prompt_tokens": p,
        "completion_tokens": c,
        "total_tokens": total,
        "cached_tokens": cached,
    }
