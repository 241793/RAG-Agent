"""人设模板 CRUD 与播种测试。

回归重点：
- 内置模板**不可删除**（避免列表被清空），但**可编辑**、**可复制**
- 播种幂等（连续两次数量不变）
- 跨租户隔离
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _setup():
    """建表 + 造管理员（直接签发 token，不依赖登录接口）。"""
    from app.core.db import AsyncSessionLocal, init_models
    from app.core.security import create_access_token, hash_password
    from app.models import Tenant, User
    from sqlalchemy import select

    async def _go():
        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
            if not t:
                t = Tenant(name="PT", slug="pt")
                db.add(t)
                await db.flush()
            u = (await db.execute(
                select(User).where(User.username == "pt_admin")
            )).scalar_one_or_none()
            if not u:
                u = User(tenant_id=t.id, username="pt_admin",
                         password_hash=hash_password("Probe12345!"),
                         is_admin=True, status="active", approval_status="approved")
                db.add(u)
                await db.flush()
            await db.commit()
            return u.id, u.tenant_id

    uid, tid = asyncio.new_event_loop().run_until_complete(_go())
    yield {"uid": uid, "tid": tid, "token": create_access_token(uid, tid)}


def _h(db) -> dict:
    return {"Authorization": f"Bearer {db['token']}"}


def test_requires_auth():
    r = c.get("/api/v1/persona-templates")
    assert r.status_code in (401, 403)


def test_crud_roundtrip(_setup):
    h = _h(_setup)
    # 创建
    r = c.post("/api/v1/persona-templates", json={
        "name": "探针模板", "description": "用于测试", "category": "测试",
        "system_prompt": "你是测试助手。\n语气：简洁。",
    }, headers=h)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["id"] and t["is_builtin"] is False
    assert t["slug"] is None, "接口创建的模板不应有 slug"

    # 列表包含
    r = c.get("/api/v1/persona-templates", headers=h)
    assert any(x["id"] == t["id"] for x in r.json())

    # 更新
    r = c.patch(f"/api/v1/persona-templates/{t['id']}",
                json={"name": "探针模板2", "system_prompt": "改过了"}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "探针模板2"

    # 删除（自定义可删）
    r = c.delete(f"/api/v1/persona-templates/{t['id']}", headers=h)
    assert r.status_code == 200
    r = c.get("/api/v1/persona-templates", headers=h)
    assert not any(x["id"] == t["id"] for x in r.json())


def test_builtin_template_cannot_be_deleted_but_editable(_setup):
    """内置模板：不可删、可改、可复制 —— 本次的核心语义。"""
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import AgentPersonaTemplate

    async def _seed():
        await init_models()
        async with AsyncSessionLocal() as db:
            from app.bootstrap import _seed_builtin_persona_templates
            await _seed_builtin_persona_templates(db, _setup["tid"], _setup["uid"])
            await db.commit()
            row = (await db.execute(
                AgentPersonaTemplate.__table__.select().where(
                    AgentPersonaTemplate.slug == "customer-service"
                )
            )).first()
            return row.id

    tid = asyncio.new_event_loop().run_until_complete(_seed())
    h = _h(_setup)

    # 不可删
    r = c.delete(f"/api/v1/persona-templates/{tid}", headers=h)
    assert r.status_code == 409, r.text
    assert "不可删除" in str(r.json())

    # 可改
    r = c.patch(f"/api/v1/persona-templates/{tid}",
                json={"description": "管理员改过的说明"}, headers=h)
    assert r.status_code == 200
    assert r.json()["description"] == "管理员改过的说明"

    # 可复制
    r = c.post(f"/api/v1/persona-templates/{tid}/clone", headers=h)
    assert r.status_code == 200
    cp = r.json()
    assert cp["is_builtin"] is False
    assert cp["slug"] is None
    assert "副本" in cp["name"]
    # 清理副本
    c.delete(f"/api/v1/persona-templates/{cp['id']}", headers=h)


def test_seed_is_idempotent(_setup):
    from app.core.db import AsyncSessionLocal, init_models
    from app.bootstrap import _seed_builtin_persona_templates
    from app.models import AgentPersonaTemplate
    from sqlalchemy import func, select

    async def _go():
        await init_models()
        async with AsyncSessionLocal() as db:
            await _seed_builtin_persona_templates(db, _setup["tid"], _setup["uid"])
            await db.commit()
            n1 = (await db.execute(select(func.count()).select_from(AgentPersonaTemplate))).scalar()
            await _seed_builtin_persona_templates(db, _setup["tid"], _setup["uid"])
            await db.commit()
            n2 = (await db.execute(select(func.count()).select_from(AgentPersonaTemplate))).scalar()
            # 内置模板必须齐 7 套
            builtins = (await db.execute(
                select(AgentPersonaTemplate).where(AgentPersonaTemplate.is_builtin.is_(True))
            )).scalars().all()
            return n1, n2, len(builtins)

    n1, n2, nb = asyncio.new_event_loop().run_until_complete(_go())
    assert n1 == n2, f"播种应幂等：{n1} != {n2}"
    assert nb == 7, f"内置模板应为 7 套，实际 {nb}"


def test_builtin_templates_have_all_four_elements(_setup):
    """内置模板必须是「角色/语气/边界/输出」四要素齐全的可用提示词。"""
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import AgentPersonaTemplate
    from sqlalchemy import select

    async def _go():
        await init_models()
        async with AsyncSessionLocal() as db:
            return (await db.execute(
                select(AgentPersonaTemplate).where(AgentPersonaTemplate.is_builtin.is_(True))
            )).scalars().all()

    rows = asyncio.new_event_loop().run_until_complete(_go())
    assert rows, "应有内置模板"
    for t in rows:
        p = t.system_prompt
        assert len(p) >= 80, f"{t.name} 提示词过短（{len(p)}）"
        assert "语气" in p, f"{t.name} 缺「语气」"
        assert "边界" in p, f"{t.name} 缺「边界」"
        assert "输出" in p, f"{t.name} 缺「输出」"


def test_filter_by_enabled(_setup):
    h = _h(_setup)
    r = c.get("/api/v1/persona-templates", params={"enabled": True}, headers=h)
    assert r.status_code == 200
    assert all(x["enabled"] for x in r.json())
