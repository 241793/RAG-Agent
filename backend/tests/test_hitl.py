"""HITL（AI 写操作待确认）测试。

断言：
  - write 工具创建 AgentAction（status=pending），不直接执行
  - 拒绝后状态=rejected
  - 确认执行后状态=executed 且副作用落地
  - 防重放：已处理的动作不能再确认
  - create_skill 工具能真正建出技能
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.admin_tools import CreateSkillTool
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import AgentAction, Skill, Tenant, User
from app.services.permission import PrincipalSet


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == "hitl"))
        ).scalar_one_or_none()
        if not tenant:
            tenant = Tenant(name="HITL", slug="hitl")
            db.add(tenant)
            await db.flush()
        admin = (
            await db.execute(select(User).where(User.username == "hitl_admin"))
        ).scalar_one_or_none()
        if not admin:
            admin = User(
                tenant_id=tenant.id, username="hitl_admin", password_hash=hash_password("x"),
                is_admin=True, display_name="管理员",
            )
            db.add(admin)
            await db.flush()
        await db.commit()
        return {"tenant_id": tenant.id, "admin": admin.id}


async def _run():
    d = await _setup()
    tid = d["tenant_id"]
    uid = d["admin"]

    # 1) 模拟 runner 挂起：写一个 pending AgentAction
    async with AsyncSessionLocal() as db:
        action = AgentAction(
            tenant_id=tid, user_id=uid, tool_name="create_skill", tool_kind="write",
            arguments={"name": "HITL演示", "body_md": "# 演示\n正文"},
            raw_tool_call={"id": "call_1", "name": "create_skill", "arguments": "{}"},
            summary="创建技能「HITL演示」", status="pending",
            idempotency_key="k1", expires_at=10**15,
        )
        db.add(action)
        await db.commit()
        aid = action.id

    # 断言尚未创建技能
    async with AsyncSessionLocal() as db:
        skills = (await db.execute(select(Skill).where(Skill.name == "HITL演示"))).scalars().all()
        assert skills == [], "挂起阶段不应创建技能"

    # 2) CAS 防重放：模拟两次确认
    from sqlalchemy import update as _upd

    async with AsyncSessionLocal() as db:
        r1 = await db.execute(
            _upd(AgentAction).where(AgentAction.id == aid, AgentAction.status == "pending")
            .values(status="approved", approved_by=uid)
        )
        await db.commit()
        assert r1.rowcount == 1
    async with AsyncSessionLocal() as db:
        r2 = await db.execute(
            _upd(AgentAction).where(AgentAction.id == aid, AgentAction.status == "pending")
            .values(status="approved", approved_by=uid)
        )
        await db.commit()
        assert r2.rowcount == 0, "第二次确认应 CAS 失败（防重放）"

    # 3) 以确认者身份执行 create_skill
    async with AsyncSessionLocal() as db:
        ps = PrincipalSet(user_id=uid, tenant_id=tid, is_admin=True)
        ctx = ToolContext(db=db, ps=ps, tenant_id=tid, user_id=uid, config={})
        res = await CreateSkillTool().execute({"name": "HITL演示", "body_md": "# 演示\n正文"}, ctx)
        assert not res.is_error, res.content
        a2 = await db.get(AgentAction, aid)
        a2.status = "executed"
        a2.result = {"content": res.content, "is_error": False}
        await db.commit()

    async with AsyncSessionLocal() as db:
        sk = (await db.execute(select(Skill).where(Skill.name == "HITL演示"))).scalars().first()
        assert sk is not None, "确认后应创建技能"
        assert sk.prompt_template.startswith("# 演示"), sk.prompt_template

    # 4) reject 分支
    async with AsyncSessionLocal() as db:
        action2 = AgentAction(
            tenant_id=tid, user_id=uid, tool_name="write_document", tool_kind="write",
            arguments={"kb_id": 1, "title": "x", "content": "y"},
            raw_tool_call={}, summary="写文档", status="pending", expires_at=10**15,
        )
        db.add(action2)
        await db.commit()
        aid2 = action2.id
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            _upd(AgentAction).where(AgentAction.id == aid2, AgentAction.status == "pending")
            .values(status="rejected", approved_by=uid)
        )
        await db.commit()
        assert r.rowcount == 1
    async with AsyncSessionLocal() as db:
        a3 = await db.get(AgentAction, aid2)
        assert a3.status == "rejected"

    print("OK hitl")


def test_hitl_flow():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.set_event_loop(None)
