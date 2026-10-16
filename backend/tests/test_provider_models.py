"""Provider「获取模型列表」测试。

回归重点：**所有驱动都必须支持 list_models**。
此前只有 openai_compat 实现了它（ollama 靠继承），anthropi/local_bge/local_hash
均缺失 —— 前端点「获取模型列表」会拿到 AttributeError。协议是 Protocol，
不会强制实现，故用测试守住这条契约。
"""
from __future__ import annotations

import asyncio

from app.services import update_service  # noqa: F401  (确保 app 包可导入)
from app.providers.drivers.anthropi import AnthropiDriver
from app.providers.drivers.local_bge import LocalBGEDriver
from app.providers.drivers.local_hash import LocalHashDriver
from app.providers.drivers.ollama import OllamaDriver
from app.providers.drivers.openai_compat import OpenAICompatibleDriver


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_every_driver_has_list_models():
    """每个驱动都要有 list_models —— 缺失会导致接口 500/报错。"""
    for cls in (AnthropiDriver, LocalBGEDriver, LocalHashDriver, OllamaDriver, OpenAICompatibleDriver):
        assert hasattr(cls, "list_models"), f"{cls.__name__} 缺少 list_models"


def test_local_hash_returns_builtin_model():
    d = LocalHashDriver(dim=32)
    models = _run(d.list_models())
    assert [m["id"] for m in models] == ["local_hash"]


def test_local_bge_returns_configured_path():
    d = LocalBGEDriver(model_path="D:/models/bge-m3")
    models = _run(d.list_models())
    assert [m["id"] for m in models] == ["D:/models/bge-m3"]


def test_anthropi_returns_known_models():
    """Anthropi 无公开 /models 端点，返回内置清单且不报错。"""
    d = AnthropiDriver(base_url="https://api.anthropi.com", api_key="x")
    models = _run(d.list_models())
    assert len(models) >= 1
    assert all(m.get("id") for m in models)
    assert any("claud" in m["id"] for m in models)


def test_ollama_inherits_openai_list_models():
    """ollama 继承 OpenAICompatibleDriver，应共享同一实现。"""
    assert OllamaDriver.list_models is OpenAICompatibleDriver.list_models
