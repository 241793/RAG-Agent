"""系统设置测试：类型转换、覆盖应用、读取脱敏、更新热生效、重启标记、权限。"""
from __future__ import annotations

import asyncio

import pytest

from app.core.db import AsyncSessionLocal, init_models
from app.core.errors import ValidationError
from app.models import SystemSetting, Tenant, User
from app.services import settings_service as S


# ---- 纯函数：类型转换 ----
def test_coerce_types():
    assert S._coerce("debug", "true") is True
    assert S._coerce("debug", "false") is False
    assert S._coerce("debug", False) is False
    assert S._coerce("port", "8080") == 8080
    assert S._coerce("retrieval_vec_min", "0.5") == 0.5
    assert S._coerce("app_name", 123) == "123"


def test_coerce_unknown_rejected():
    with pytest.raises(ValidationError):
        S._coerce("nonexistent_key", 1)


def test_coerce_bad_int_rejected():
    with pytest.raises(ValidationError):
        S._coerce("port", "abc")


def test_field_meta_covers_core_keys():
    for k in ("port", "database_url", "retrieval_top_k", "security_guard_enabled",
              "mcp_allow_stdio", "secret_key", "storage_local_dir"):
        assert k in S.FIELD_META, f"缺少字段元数据：{k}"


def test_secret_masked_in_config():
    cfg = {c["key"]: c for c in S.get_config()}
    assert cfg["secret_key"]["value"] == "••••••"
    assert cfg["secret_key"]["is_set"] is True
    # 非敏感项正常返回值
    assert cfg["retrieval_top_k"]["value"] is not None


def test_restart_flags():
    cfg = {c["key"]: c for c in S.get_config()}
    assert cfg["port"]["restart"] is True
    assert cfg["retrieval_top_k"]["restart"] is False


# ---- DB 级 ----
async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(__import__("sqlalchemy").select(Tenant).where(Tenant.slug == "set-t1"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="SET", slug="set-t1")
            db.add(t)
            await db.flush()
            u = User(tenant_id=t.id, username="set_admin", display_name="sa", is_admin=True,
                     password_hash="x")
            db.add(u)
            await db.flush()
            await db.commit()
            return {"tenant_id": t.id, "user_id": u.id}
        u = (await db.execute(__import__("sqlalchemy").select(User).where(User.username == "set_admin"))).scalar_one()
        return {"tenant_id": t.id, "user_id": u.id}


async def _apply_and_update():
    d = await _setup()
    from app.core.config import settings

    orig_topk = settings.retrieval_top_k
    orig_port = settings.port
    async with AsyncSessionLocal() as db:
        # 清理历史行，保证幂等
        from sqlalchemy import delete

        await db.execute(delete(SystemSetting).where(SystemSetting.key.in_(["retrieval_top_k", "port"])))
        await db.commit()
    # 1) apply_overrides：预先写库 → 叠加生效
    async with AsyncSessionLocal() as db:
        db.add(SystemSetting(key="retrieval_top_k", value=9))
        await db.commit()
    async with AsyncSessionLocal() as db:
        n = await S.apply_overrides(db)
    assert n >= 1
    assert settings.retrieval_top_k == 9

    # 2) update_config：热项即改即生效，restart_required=False
    async with AsyncSessionLocal() as db:
        r = await S.update_config(db, user_id=d["user_id"], updates={"retrieval_top_k": 3})
        await db.commit()
    assert settings.retrieval_top_k == 3
    assert r["restart_required"] is False
    assert "retrieval_top_k" in r["changed"]

    # 3) 改 port → restart_required=True
    async with AsyncSessionLocal() as db:
        r2 = await S.update_config(db, user_id=d["user_id"], updates={"port": 7099})
        await db.commit()
    assert settings.port == 7099
    assert r2["restart_required"] is True

    # 4) secret 掩码值 = 跳过
    async with AsyncSessionLocal() as db:
        r3 = await S.update_config(db, user_id=d["user_id"], updates={"secret_key": "••••••"})
        await db.commit()
    assert "secret_key" not in r3["changed"]

    # 5) 未知 key 抛错
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await S.update_config(db, user_id=d["user_id"], updates={"nope": 1})

    # 还原
    settings.retrieval_top_k = orig_topk
    settings.port = orig_port
    print("OK settings_apply_update")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_apply_and_update():
    _run_async(_apply_and_update())


# ---- API 权限 ----
def test_settings_endpoint_registered():
    from app.api.v1.settings import router

    paths = {r.path for r in router.routes}
    assert "/system/settings" in paths
    assert any("restart" in p for p in paths)


def test_system_manage_permission_seeded():
    from app.services.permission_seed import PERMISSIONS

    assert "system:manage" in [p[0] for p in PERMISSIONS]
