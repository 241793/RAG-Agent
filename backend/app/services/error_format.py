"""把入库/处理阶段的异常格式化成结构化的报错，供前端展示与修复建议。"""
from __future__ import annotations

from app.core.errors import UpstreamError


def _suggest(status_code: int | None, purpose: str | None, message: str) -> str:
    low = (message or "").lower()
    # 「完全没配 embedding 模型」优先识别（消息来自 registry.get_embedding 的 ValidationError）
    if purpose == "embedding" and ("未配置向量模型" in message or "no model" in low or "未配置" in message):
        return ("未配置可用的向量模型。两条路选一：①在「模型管理」配置一个 embedding 模型后「重新处理」；"
                "②把该知识库的「索引方式」改为『纯关键词』——不需要任何向量模型即可用（适合术语/编号/短条目）。")
    if status_code == 404:
        if purpose == "embedding":
            return ("上游端点返回 404：该地址很可能不提供 /embeddings 接口（常见于把对话模型配成了向量模型）。"
                    "请在「模型管理」里为 embedding 用途单独配置一个支持 embeddings 的模型，"
                    "或改用本地向量模型（Provider 类型选 local_hash，可离线运行）。")
        return "上游端点返回 404：请核对 base_url 是否拼写正确、接口路径是否为该服务实际提供。"
    if status_code in (401, 403):
        return "鉴权失败：请检查 API Key 是否正确、是否有权限访问该模型。"
    if status_code == 429:
        return "上游限流（429）：请降低并发/频率，或稍后重试。"
    if status_code and status_code >= 500:
        return "上游服务错误：请稍后重试，或联系上游服务提供方。"
    if "timeout" in low or "timed out" in low:
        return "请求超时：请检查网络连通性、上游负载，或调大 Provider 的超时设置。"
    if "connect" in low or "connection" in low:
        return "无法连接上游：请确认 base_url 可达（服务已启动、端口正确、无防火墙拦截）。"
    return "请根据上方「详细错误」排查上游配置（base_url / api_key / 模型名）。"


def format_ingest_error(e: Exception, *, stage: str = "embedding") -> dict:
    """返回结构化错误详情 dict（可 JSON 序列化，存入 Document.error_detail）。"""
    if isinstance(e, UpstreamError):
        summary = f"{stage} 阶段调用上游失败"
        detail = str(e)
        return {
            "stage": stage,
            "summary": summary,
            "detail": detail,
            "provider": e.provider,
            "base_url": e.base_url,
            "model": e.model,
            "status_code": e.upstream_status,
            "raw": e.raw,
            "suggestion": _suggest(e.upstream_status, e.purpose or stage, detail),
        }

    msg = str(e)
    # 从字符串里尽力抽取失败阶段与截断原文
    summary = f"{stage} 阶段失败"
    return {
        "stage": stage,
        "summary": summary,
        "detail": msg,
        "provider": None,
        "base_url": None,
        "model": None,
        "status_code": None,
        "raw": None,
        "suggestion": _suggest(None, stage, msg),
    }


def short_summary(err: dict) -> str:
    """给 error_msg（短字段）用的一行摘要。"""
    parts = [err.get("summary") or "处理失败"]
    if err.get("status_code"):
        parts.append(f"HTTP {err['status_code']}")
    if err.get("model"):
        parts.append(f"model={err['model']}")
    return " · ".join(parts)
