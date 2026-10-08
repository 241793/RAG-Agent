"""连接器注册表：按 kind 构建连接器实例（与 providers/registry.py 同构）。"""
from __future__ import annotations

from typing import Any

from app.core.crypto import decrypt
from app.core.errors import ValidationError

# kind → (构造配置指纹) → 实例。指纹含解密后内容，避免改配置后命中旧实例。
_CACHE: dict[tuple, Any] = {}


def build_connector(kind: str, config: dict, *, kb_id: int = 0, timeout: int = 15):
    config = config or {}
    fp = (kind, kb_id, timeout, str(sorted((k, str(v)) for k, v in config.items())))
    if fp in _CACHE:
        return _CACHE[fp]

    from app.connectors.drivers.generic_http import GenericHttpConnector

    if kind == "generic_http":
        conn = GenericHttpConnector(kb_id=kb_id, config=config, timeout=timeout)
    elif kind == "dify":
        from app.connectors.drivers.dify import DifyConnector

        conn = DifyConnector(kb_id=kb_id, config=config, timeout=timeout)
    elif kind in ("ragflow", "fastgpt"):
        from app.connectors.drivers.ragflow import RagflowConnector

        conn = RagflowConnector(kb_id=kb_id, config=config, timeout=timeout, kind=kind)
    elif kind == "mcp":
        from app.connectors.drivers.mcp import McpConnector

        conn = McpConnector(kb_id=kb_id, config=config, timeout=timeout)
    elif kind == "sql_db":
        from app.connectors.drivers.sql_db import SqlConnector

        conn = SqlConnector(kb_id=kb_id, config=config, timeout=timeout)
    elif kind == "feishu_sheet":
        from app.connectors.drivers.feishu_sheet import FeishuSheetConnector

        conn = FeishuSheetConnector(kb_id=kb_id, config=config, timeout=timeout)
    elif kind in ("google_sheet", "gsheet"):
        from app.connectors.drivers.google_sheet import GoogleSheetConnector

        conn = GoogleSheetConnector(kb_id=kb_id, config=config, timeout=timeout)
    else:
        raise ValidationError(f"不支持的连接器类型: {kind}")

    _CACHE[fp] = conn
    return conn


def from_kb(kb) -> Any | None:
    """从 KnowledgeBase 行构建连接器；非外部源返回 None。"""
    if getattr(kb, "source_type", "local") != "external":
        return None
    if not kb.connector_kind:
        raise ValidationError(f"知识库「{kb.name}」标记为外部源但未配置连接器类型")
    from app.core.config import settings

    cfg = dict(kb.connector_config or {})
    if cfg.get("api_key"):
        cfg["api_key"] = decrypt(cfg["api_key"])
    return build_connector(
        kb.connector_kind, cfg, kb_id=kb.id,
        timeout=int(cfg.get("timeout") or settings.connector_default_timeout),
    )


def invalidate_cache() -> None:
    _CACHE.clear()
