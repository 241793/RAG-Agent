"""首次运行初始化：默认租户、管理员、默认 Provider 与模型配置、权限角色。

被 scripts/seed.py 与桌面启动入口 run_server.py 复用（幂等）。
放在 app 包内以确保 PyInstaller 能收集。
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import ModelConfig, ModelProvider, Tenant, User


async def seed_all() -> None:
    """幂等播种。已存在的数据跳过。"""
    await init_models()
    async with AsyncSessionLocal() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == "default"))
        ).scalar_one_or_none()
        if not tenant:
            tenant = Tenant(name="默认组织", slug="default", plan="default")
            db.add(tenant)
            await db.flush()

        admin = (
            await db.execute(
                select(User).where(User.tenant_id == tenant.id, User.username == "admin")
            )
        ).scalar_one_or_none()
        if not admin:
            admin = User(
                tenant_id=tenant.id,
                username="admin",
                display_name="系统管理员",
                email="admin@example.com",
                password_hash=hash_password("admin123"),
                is_admin=True,
            )
            db.add(admin)
            await db.flush()

        has_provider = (await db.execute(select(ModelProvider))).scalars().first()
        if not has_provider and (
            settings.default_llm_api_key or settings.default_embedding_api_key
        ):
            base = settings.default_llm_base_url or settings.default_embedding_base_url
            key = settings.default_llm_api_key or settings.default_embedding_api_key
            provider = ModelProvider(
                tenant_id=tenant.id, name="默认云端 Provider", kind="openai",
                base_url=base, api_key=key,
            )
            db.add(provider)
            await db.flush()
            if settings.default_llm_model:
                db.add(ModelConfig(
                    tenant_id=tenant.id, provider_id=provider.id, purpose="chat",
                    model_name=settings.default_llm_model, display_name=settings.default_llm_model,
                    is_default=True, priority=10,
                ))
            if settings.default_embedding_model:
                db.add(ModelConfig(
                    tenant_id=tenant.id, provider_id=provider.id, purpose="embedding",
                    model_name=settings.default_embedding_model, display_name=settings.default_embedding_model,
                    embedding_dim=settings.embedding_dim, is_default=True, priority=10,
                ))

        from app.services.permission_seed import (
            backfill_admin_super,
            backfill_viewer_role,
            seed_permissions_and_roles,
        )

        role_ids = await seed_permissions_and_roles(db)
        await backfill_admin_super(db, tenant.id, role_ids)
        await backfill_viewer_role(db, tenant.id, role_ids)
        await _backfill_external_users(db)

        # 叠加 Web 端系统设置的覆盖值（启动早期，确保端口等启动期项生效）
        from app.services.settings_service import apply_overrides

        await apply_overrides(db)

        await db.commit()


async def _backfill_external_users(db) -> None:
    """存量渠道虚拟用户回填 user_type=external（幂等）。

    旧版本把外部客户建成普通 User，username 形如 {kind}_{external_id}；
    另有大量历史账号 user_type 为 NULL（该列后加），统一回填为 internal。
    """
    from sqlalchemy import or_
    from sqlalchemy import update as _upd

    for kind in ("qqbot", "wxclaw", "wework", "feishu"):
        await db.execute(
            _upd(User).where(
                User.username.like(f"{kind}_%"),
                or_(User.user_type.is_(None), User.user_type != "external"),
            ).values(user_type="external")
        )
    # 剩余 NULL → internal（避免 SQL 中 != 'external' 对 NULL 求值为假而漏掉账号）
    await db.execute(
        _upd(User).where(User.user_type.is_(None)).values(user_type="internal")
    )
    await db.flush()
