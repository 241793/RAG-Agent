"""模型 Provider 配置接口：Provider/模型配置 CRUD + 连接测试。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.middleware.auth_dep import get_current_user, require_admin, require_permission
from app.services.audit_service import audited
from app.models import ModelConfig, ModelProvider, User
from app.providers.base import ChatMessage
from app.providers.registry import _build_driver, invalidate_cache
from app.schemas.provider import (
    ModelConfigCreate,
    ModelConfigOut,
    ProviderCreate,
    ProviderOut,
    ProviderTestRequest,
    ProviderTestResult,
    ProviderUpdate,
)

router = APIRouter(prefix="/providers", tags=["provider"])


def _to_out(p: ModelProvider) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        kind=p.kind,
        base_url=p.base_url,
        api_key_set=bool(p.api_key),
        status=p.status,
        health_status=p.health_status,
        last_check_at=p.last_check_at,
        timeout=p.timeout,
        extra_headers=p.extra_headers,
    )


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    user: User = Depends(require_permission("model:read")), db: AsyncSession = Depends(get_db)
) -> list[ProviderOut]:
    rows = (
        await db.execute(
            select(ModelProvider).where(
                (ModelProvider.tenant_id == user.tenant_id) | (ModelProvider.tenant_id.is_(None))
            )
        )
    ).scalars().all()
    return [_to_out(p) for p in rows]


@router.post("", response_model=ProviderOut)
@audited("provider.create", "model_provider")
async def create_provider(
    body: ProviderCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    p = ModelProvider(
        tenant_id=user.tenant_id,
        name=body.name,
        kind=body.kind,
        base_url=body.base_url,
        api_key=body.api_key,
        extra_headers=body.extra_headers,
        timeout=body.timeout,
        max_retries=body.max_retries,
    )
    db.add(p)
    await db.flush()
    invalidate_cache()
    return _to_out(p)


@router.patch("/{provider_id}", response_model=ProviderOut)
@audited("provider.update", "model_provider", id_arg="provider_id")
async def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    p = await db.get(ModelProvider, provider_id)
    if not p:
        raise NotFoundError("Provider 不存在")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(p, field, val)
    await db.flush()
    invalidate_cache()
    return _to_out(p)


@router.delete("/{provider_id}")
@audited("provider.delete", "model_provider", id_arg="provider_id")
async def delete_provider(
    provider_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    p = await db.get(ModelProvider, provider_id)
    if not p:
        raise NotFoundError("Provider 不存在")
    await db.delete(p)
    invalidate_cache()
    return {"message": "已删除"}


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(
    provider_id: int,
    body: ProviderTestRequest,
    user: User = Depends(require_permission("model:read")),
    db: AsyncSession = Depends(get_db),
) -> ProviderTestResult:
    p = await db.get(ModelProvider, provider_id)
    if not p:
        raise NotFoundError("Provider 不存在")
    drv = _build_driver(p.kind, p.base_url, p.api_key, p.timeout, p.extra_headers)
    t0 = time.time()
    try:
        if body.purpose == "embedding":
            model = body.model_name
            if not model:
                mc = (
                    await db.execute(
                        select(ModelConfig).where(
                            ModelConfig.provider_id == provider_id, ModelConfig.purpose == "embedding"
                        )
                    )
                ).scalars().first()
                model = mc.model_name if mc else "text-embedding-3-small"
            vecs = await drv.embed([body.text or "测试文本"], model=model)
            return ProviderTestResult(
                ok=True, latency_ms=int((time.time() - t0) * 1000), message=f"向量维度={len(vecs[0])}"
            )
        else:
            model = body.model_name
            if not model:
                mc = (
                    await db.execute(
                        select(ModelConfig).where(
                            ModelConfig.provider_id == provider_id, ModelConfig.purpose == "chat"
                        )
                    )
                ).scalars().first()
                model = mc.model_name if mc else "gpt-4o-mini"
            res = await drv.chat([ChatMessage(role="user", content=body.text or "你好")], model=model)
            return ProviderTestResult(
                ok=True,
                latency_ms=int((time.time() - t0) * 1000),
                message=f"回复: {res.content[:80]}",
            )
    except Exception as e:  # noqa: BLE001
        return ProviderTestResult(ok=False, latency_ms=int((time.time() - t0) * 1000), message=str(e)[:300])


@router.post("/{provider_id}/health")
async def check_provider_health(
    provider_id: int,
    purpose: str = "chat",
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """对 Provider 做一次健康检查，回写 health_status / last_check_at。"""
    from app.core.errors import UpstreamError

    p = await db.get(ModelProvider, provider_id)
    if not p:
        raise NotFoundError("Provider 不存在")
    drv = _build_driver(p.kind, p.base_url, p.api_key, p.timeout, p.extra_headers)
    t0 = time.time()
    ok = False
    message = ""
    try:
        try:
            h = await drv.health(purpose=purpose)
        except TypeError:
            h = await drv.health()  # 部分驱动 health() 不接受 purpose
        ok = bool(getattr(h, "ok", False))
        message = getattr(h, "message", "") or ("正常" if ok else "失败")
    except Exception as e:  # noqa: BLE001
        detail = str(e)
        if isinstance(e, UpstreamError):
            detail = str(e)
        message = detail[:300]

    p.health_status = "ok" if ok else "fail"
    p.last_check_at = int(time.time() * 1000)
    await db.flush()
    return {
        "ok": ok, "message": message, "latency_ms": int((time.time() - t0) * 1000),
        "health_status": p.health_status,
        "last_check_at": p.last_check_at,
    }


# ---- 模型配置 ----
@router.get("/configs/all", response_model=list[ModelConfigOut])
async def list_model_configs(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ModelConfigOut]:
    rows = (
        await db.execute(
            select(ModelConfig).where(
                (ModelConfig.tenant_id == user.tenant_id) | (ModelConfig.tenant_id.is_(None))
            )
        )
    ).scalars().all()
    return [ModelConfigOut.model_validate(r) for r in rows]


@router.post("/configs", response_model=ModelConfigOut)
@audited("model_config.create", "model_config")
async def create_model_config(
    body: ModelConfigCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ModelConfigOut:
    mc = ModelConfig(
        tenant_id=user.tenant_id,
        provider_id=body.provider_id,
        purpose=body.purpose,
        model_name=body.model_name,
        display_name=body.display_name or body.model_name,
        params=body.params,
        embedding_dim=body.embedding_dim,
        is_default=body.is_default,
        priority=body.priority,
    )
    db.add(mc)
    await db.flush()
    invalidate_cache()
    return ModelConfigOut.model_validate(mc)


@router.get("/{provider_id}/models")
async def list_provider_models(
    provider_id: int,
    user: User = Depends(require_permission("model:read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """拉取该 Provider 的可用模型列表（调用远端 /v1/models）。"""
    p = await db.get(ModelProvider, provider_id)
    if not p:
        raise NotFoundError("Provider 不存在")
    drv = _build_driver(p.kind, p.base_url, p.api_key, p.timeout, p.extra_headers)
    try:
        models = await drv.list_models()
        return {"ok": True, "models": models}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "models": [], "message": str(e)[:300]}


class ModelConfigUpdate(BaseModel):
    model_name: str | None = None
    display_name: str | None = None
    purpose: str | None = None
    params: dict | None = None
    embedding_dim: int | None = None
    is_default: bool | None = None
    priority: int | None = None
    status: str | None = None


@router.patch("/configs/{config_id}", response_model=ModelConfigOut)
@audited("model_config.update", "model_config", id_arg="config_id")
async def update_model_config(
    config_id: int,
    body: ModelConfigUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ModelConfigOut:
    mc = await db.get(ModelConfig, config_id)
    if not mc or mc.tenant_id != user.tenant_id:
        raise NotFoundError("模型配置不存在")
    # 设为默认时，把同 purpose 的其它配置取消默认
    if body.is_default:
        others = (
            await db.execute(
                select(ModelConfig).where(
                    ModelConfig.tenant_id == mc.tenant_id,
                    ModelConfig.purpose == (body.purpose or mc.purpose),
                    ModelConfig.id != mc.id,
                )
            )
        ).scalars().all()
        for o in others:
            o.is_default = False
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(mc, k, v)
    await db.flush()
    invalidate_cache()
    return ModelConfigOut.model_validate(mc)


@router.delete("/configs/{config_id}")
@audited("model_config.delete", "model_config", id_arg="config_id")
async def delete_model_config(
    config_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    mc = await db.get(ModelConfig, config_id)
    if not mc or mc.tenant_id != user.tenant_id:
        raise NotFoundError("模型配置不存在")
    await db.delete(mc)
    await db.flush()
    invalidate_cache()
    return {"message": "已删除"}
