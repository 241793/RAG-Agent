"""Ollama 原生驱动占位（本地部署时实现 /api/chat 与 /api/embeddings）。

当前直接复用 OpenAI 兼容驱动（Ollama 提供 /v1 兼容层）即可。
"""
from __future__ import annotations

from app.providers.drivers.openai_compat import OpenAICompatibleDriver


class OllamaDriver(OpenAICompatibleDriver):
    """Ollama 默认在 :11434，兼容 /v1。可直接用 OpenAICompatibleDriver 指向
    http://localhost:11434/v1 即可。此类保留用于后续接入原生 API（模型管理、拉取等）。
    """

    pass
