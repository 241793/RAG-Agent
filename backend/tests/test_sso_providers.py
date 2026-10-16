"""SSO 提供者列表与配置可用性测试。

回归重点：/supported 必须列出**所有已实现**的提供者类型，
不依赖是否已存在配置 —— 否则新部署时配置页无从下手（死锁）。
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sso_providers import PROVIDERS, supported_providers

c = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _init_db():
    """建表并造一个管理员，供需要鉴权的用例使用。

    conftest 只设置了测试库路径，建表与种子由测试自行触发。
    """
    from app.core.db import AsyncSessionLocal, init_models
    from app.core.security import hash_password, create_access_token
    from app.models import Tenant, User
    from sqlalchemy import select

    async def _setup():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
            if not t:
                t = Tenant(name="SSO_T", slug="ssot")
                db.add(t)
                await db.flush()
            u = (await db.execute(
                select(User).where(User.username == "sso_probe_admin")
            )).scalar_one_or_none()
            if not u:
                u = User(tenant_id=t.id, username="sso_probe_admin",
                         password_hash=hash_password("Probe12345!"),
                         is_admin=True, status="active", approval_status="approved")
                db.add(u)
                await db.flush()
            await db.commit()
            return u.id, u.tenant_id

    loop = asyncio.new_event_loop()
    uid, tid = loop.run_until_complete(_setup())
    yield {"uid": uid, "tid": tid, "token": create_access_token(uid, tid)}


def _token(_db=None) -> str:
    return _db["token"]


def test_supported_covers_all_implemented_providers():
    """supported_providers() 必须覆盖 PROVIDERS 里每一个已实现的类型。"""
    got = {m["provider"] for m in supported_providers()}
    assert got == set(PROVIDERS.keys()), f"缺: {set(PROVIDERS.keys()) - got}"


def test_supported_has_name_and_help():
    for m in supported_providers():
        assert m.get("name"), f"{m['provider']} 缺 name（前端无法显示）"
        assert m.get("help"), f"{m['provider']} 缺 help"


def test_supported_endpoint_returns_all_regardless_of_config(_init_db):
    """关键回归：即便一条配置都没有，也必须返回全部可选类型。

    这正是此前的死锁 —— 配置页只列「已启用」项，而新部署全是空的。
    """
    t = _token(_init_db)
    r = c.get("/api/v1/auth/sso/supported", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == len(PROVIDERS)
    assert {i["provider"] for i in items} == set(PROVIDERS.keys())


def test_supported_requires_permission():
    """未登录不得访问（配置页专用）。"""
    r = c.get("/api/v1/auth/sso/supported")
    assert r.status_code in (401, 403)


def test_supported_is_not_shadowed_by_provider_route(_init_db):
    """路由顺序回归：/supported 是单段，不能被 /{provider}/login 之类吃掉。"""
    t = _token(_init_db)
    r = c.get("/api/v1/auth/sso/supported", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_empty_providers_is_still_empty_list():
    """公开的 /providers 语义不变：只列已启用的，未配置时为空。"""
    r = c.get("/api/v1/auth/sso/providers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
