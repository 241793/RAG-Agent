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
        await _seed_builtin_agents(db, tenant.id, admin.id)

        # 叠加 Web 端系统设置的覆盖值（启动早期，确保端口等启动期项生效）
        from app.services.settings_service import apply_overrides

        await apply_overrides(db)

        await db.commit()


async def _seed_builtin_agents(db, tenant_id: int, admin_id: int) -> None:
    """播种平台内置智能体（幂等，按 slug 去重）。

    约定：内置体**不预置 model_config_id**——对话模型由使用者在界面自行选择，
    避免种子阶段把某个尚未配置的模型写死；工具默认全开，使用者可按需关闭。
    """
    from app.models import Agent

    builtins = [
        {
            "slug": "group-manager",
            "name": "QQ管理助手",
            "description": "企业级群管机器人：被 @ 时可执行禁言、移人、设管理员、发公告、置顶/撤回、搜消息、查统计、创建定时任务（日报周报月报、夜间静默）。需先设为群管理员才具备管理权限。",
            "system_prompt": (
                "你是本平台的企业群管助手。被 @ 时按用户意图行动：\n"
                "1) 要「看效果/要一段代码」→ 直接输出 ```html 代码块（前端可预览，零副作用），不要调用 generate_file；\n"
                "2) 明确要「文件/下载/导出」→ 才调用 generate_file 生成；\n"
                "3) 群管理操作（禁言/移人/设管理员/公告/置顶/撤回/搜消息/统计/定时任务）→ 调用对应的 room_* 工具；若无权限，说明需要先把你设为群管理员。\n"
                "回答用 Markdown，引用资料标注 [n]，不编造引用编号。"
            ),
            "type": "agent",
            "status": "published",
            "visibility": "tenant",
            "is_builtin": True,
            "tool_config": {"max_turns": 8},
            "config": {"temperature": 0.3},
        },
    ]
    for spec in builtins:
        exist = (
            await db.execute(
                select(Agent).where(Agent.tenant_id == tenant_id, Agent.slug == spec["slug"])
            )
        ).scalar_one_or_none()
        if exist:
            # 已存在则仅补齐内置标记（兼容历史数据），避免覆盖使用者的自定义改动
            if not exist.is_builtin:
                exist.is_builtin = True
                await db.flush()
            continue
        db.add(Agent(
            tenant_id=tenant_id, owner_id=admin_id, name=spec["name"], slug=spec["slug"],
            description=spec["description"], type=spec.get("type", "agent"),
            system_prompt=spec.get("system_prompt", ""),
            model_config_id=spec.get("model_config_id"),  # 内置体不预置模型
            tool_config=spec.get("tool_config"),
            config=spec.get("config"),
            status=spec.get("status", "published"),
            visibility=spec.get("visibility", "tenant"),
            is_builtin=True,
        ))
        await db.flush()


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
