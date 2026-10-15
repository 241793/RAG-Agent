"""上游 HTTP 调用的重试辅助：仅对「可恢复」错误做指数退避重试。

可恢复：超时、连接/网络错误、429、5xx。不可重试：其余 4xx（鉴权/参数错误——重试无意义）。
由驱动类混入 RetryMixin 使用。
"""
from __future__ import annotations

import asyncio

import httpx


class RetryMixin:
    """给驱动类提供带指数退避的请求方法。驱动需在 __init__ 里设置 self.max_retries。

    重试策略：0.5s → 1s → 2s …（封顶 8s）。max_retries 为「额外重试次数」，
    即最多请求 1 + max_retries 次。
    """

    max_retries: int = 2

    @staticmethod
    def _is_retryable(err: Exception) -> bool:
        if isinstance(err, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
            return True
        if isinstance(err, httpx.HTTPStatusError):
            code = err.response.status_code
            return code == 429 or 500 <= code < 600
        return False

    async def _request_with_retry(
        self, client: httpx.AsyncClient, method: str, url: str, **kw
    ) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = await client.request(method, url, **kw)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    if attempt >= self.max_retries:
                        resp.raise_for_status()
                        return resp  # 不可达（上面已抛）
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp
            except Exception as e:  # noqa: BLE001
                if attempt >= self.max_retries or not self._is_retryable(e):
                    raise
                await asyncio.sleep(min(0.5 * (2 ** attempt), 8.0))
                attempt += 1
