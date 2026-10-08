"""内存令牌桶限流（零依赖，单进程）。

多进程/多副本场景不精确；需要精确时换 Redis。
"""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self) -> None:
        # key -> (tokens, last_refill_ts)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str, rate_per_min: int, burst: int | None = None) -> bool:
        if rate_per_min <= 0:
            return True
        capacity = float(burst or rate_per_min)
        rate_per_sec = rate_per_min / 60.0
        now = time.monotonic()
        async with self._lock:
            tokens, last = self._buckets.get(key, (capacity, now))
            # 补桶
            tokens = min(capacity, tokens + (now - last) * rate_per_sec)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True
            self._buckets[key] = (tokens, now)
            return False


rate_limiter = TokenBucket()
