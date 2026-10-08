"""本地 bge 系列驱动占位（FlagEmbedding / TEI）。

启用方式：pip install FlagEmbedding，然后在此实现 embed/rerank 调用本地模型
（bge-m3 做 embedding，bge-reranker-v2-m3 做重排）。当前留接口，保证 Provider
抽象层完整，切换时无需改动上层。
"""
from __future__ import annotations

from app.providers.base import ProviderHealth


class LocalBGEDriver:
    def __init__(self, *, model_path: str, device: str = "cpu") -> None:
        self.model_path = model_path
        self.device = device
        self._model = None

    def _lazy_load(self):
        try:
            from FlagEmbedding import FlagModel  # type: ignore
        except ImportError as e:  # noqa: BLE001
            raise RuntimeError("未安装 FlagEmbedding，请 pip install FlagEmbedding") from e
        if self._model is None:
            self._model = FlagModel(self.model_path, device=self.device)
        return self._model

    async def embed(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        import asyncio

        def _run():
            model = self._lazy_load()
            vecs = model.encode(texts, batch_size=batch_size, normalize_embeddings=True)
            return [list(map(float, v)) for v in vecs]

        return await asyncio.to_thread(_run)

    async def health(self) -> ProviderHealth:
        try:
            self._lazy_load()
            return ProviderHealth(ok=True, message="本地模型就绪")
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:200])
