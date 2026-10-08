"""管理员 AI 操作工具测试：工具注册、定时任务服务、create/delete、一次性提醒。"""
from __future__ import annotations

import time

import pytest


# ---- 工具注册 ----
def test_all_ops_tools_registered():
    from app.agents.tools.registry import registry

    names = {t.name for t in registry.all_admin()}
    must = {
        "create_scheduled_task", "update_scheduled_task", "delete_scheduled_task", "run_scheduled_task_now",
        "create_user", "update_user", "create_role", "set_role_permissions", "create_dept",
        "create_group", "grant_user_role", "create_kb", "delete_kb", "remove_kb_member",
        "update_agent", "publish_agent", "delete_agent", "create_api_key", "revoke_api_key",
        "batch_delete_documents", "batch_move_documents", "set_doc_visibility",
        "reprocess_document", "update_document_tags", "create_channel", "delete_channel",
        "save_workflow", "create_model_config",
    }
    missing = must - names
    assert not missing, f"缺少工具：{missing}"


def test_write_tools_declare_permission_and_summarize():
    from app.agents.tools.ops_tools import OPS_TOOLS

    for t in OPS_TOOLS:
        assert getattr(t, "kind", "") == "write", t.name
        assert getattr(t, "required_permission", None), f"{t.name} 缺权限声明"
        assert hasattr(t, "summarize")
        # summarize 不应抛错
        t.summarize({"kb_id": 1, "doc_id": 1, "task_id": 1, "user_id": 1, "role_id": 1,
                     "agent_id": 1, "channel_id": 1, "key_id": 1, "ids": [1, 2],
                     "name": "x", "kind": "wxclaw", "tags": ["a"], "visibility": "public"})


def test_ops_tools2_registered():
    """第二轮工具全部注册。"""
    from app.agents.tools.registry import registry

    names = {t.name for t in registry.all_admin()}
    must = {
        "clone_agent", "manage_agent_version", "manage_agent_mode",
        "update_skill", "delete_skill", "toggle_skill_scripts",
        "register_tool", "delete_tool", "test_tool",
        "manage_provider", "manage_model_config", "test_kb_connector",
        "manage_doc_acl", "delete_folder", "update_channel", "test_channel",
        "manage_role", "revoke_user_role", "manage_dept", "manage_group",
        "manage_webhook_token", "publish_workflow",
    }
    missing = must - names
    assert not missing, f"缺少第二轮工具：{missing}"


def test_ops_tools2_write_tools_valid():
    from app.agents.tools.ops_tools2 import OPS_TOOLS2

    sample = {"action": "create", "agent_id": 1, "mode_id": 1, "name": "x", "skill_id": 1,
              "tool_id": 1, "provider_id": 1, "config_id": 1, "task_id": 1, "token_id": 1,
              "doc_id": 1, "folder_id": 1, "channel_id": 1, "group_id": 1, "role_id": 1,
              "user_role_id": 1, "dept_id": 1, "principal_type": "department", "principal_id": 2,
              "enabled": True, "url": "http://x"}
    for t in OPS_TOOLS2:
        if getattr(t, "kind", "") == "write":
            assert getattr(t, "required_permission", None), f"{t.name} 缺权限声明"
            t.summarize(sample)  # 不应抛错


@pytest.mark.asyncio
async def test_manage_agent_mode_actions():
    from app.agents.tools.base import ToolContext
    from app.agents.tools.ops_tools2 import ManageAgentModeTool
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Agent, Tenant
    from app.services.permission import PrincipalSet

    await init_models()
    async with AsyncSessionLocal() as db:
        ten = Tenant(name="M", slug="m-agent-mode")
        db.add(ten); await db.flush()
        ag = Agent(tenant_id=ten.id, owner_id=1, name="a", slug="am", type="agent", system_prompt="")
        db.add(ag); await db.flush()
        ctx = ToolContext(db=db, ps=PrincipalSet(user_id=1, tenant_id=ten.id), tenant_id=ten.id, user_id=1)
        tool = ManageAgentModeTool()
        r1 = await tool.execute({"action": "create", "agent_id": ag.id, "name": "模式1"}, ctx)
        assert not r1.is_error and r1.data.get("id")
        mid = r1.data["id"]
        r2 = await tool.execute({"action": "update", "agent_id": ag.id, "mode_id": mid, "name": "模式1改"}, ctx)
        assert not r2.is_error
        r3 = await tool.execute({"action": "delete", "agent_id": ag.id, "mode_id": mid}, ctx)
        assert not r3.is_error


@pytest.mark.asyncio
async def test_add_kb_member_by_department():
    """add_kb_member 支持 principal_type=department（修功能缺口）。"""
    from app.agents.tools.base import ToolContext
    from app.agents.tools.platform_tools import AddKbMemberTool
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import KBMember, KnowledgeBase, Tenant
    from app.services.permission import PrincipalSet, dept_principal
    from sqlalchemy import select

    await init_models()
    async with AsyncSessionLocal() as db:
        ten = Tenant(name="D", slug="d-member")
        db.add(ten); await db.flush()
        kb = KnowledgeBase(tenant_id=ten.id, name="k", visibility="private", owner_id=1)
        db.add(kb); await db.flush()
        ctx = ToolContext(db=db, ps=PrincipalSet(user_id=1, tenant_id=ten.id), tenant_id=ten.id, user_id=1)
        r = await AddKbMemberTool().execute(
            {"kb_id": kb.id, "principal_type": "department", "principal_id": 5, "perm_level": "editor"}, ctx)
        assert not r.is_error
        row = (await db.execute(select(KBMember).where(
            KBMember.kb_id == kb.id, KBMember.principal_id == dept_principal(5)))).scalar_one_or_none()
        assert row is not None and row.perm_level == "editor"


# ---- schedule_service ----
def test_schedule_service_validate():
    from app.core.errors import ValidationError
    from app.services.schedule_service import validate_schedule

    # cron 非法
    with pytest.raises(ValidationError):
        validate_schedule({"schedule_kind": "cron", "cron_expr": "bad"})
    # interval < 60
    with pytest.raises(ValidationError):
        validate_schedule({"schedule_kind": "interval", "interval_seconds": 10})
    # once 缺 run_at
    with pytest.raises(ValidationError):
        validate_schedule({"schedule_kind": "once"})
    # 合法 cron
    validate_schedule({"schedule_kind": "cron", "cron_expr": "0 9 * * *"})


def test_schedule_compute_next_once():
    from app.models import ScheduledTask
    from app.services.schedule_service import compute_next

    t = ScheduledTask(tenant_id=1, owner_id=1, agent_id=1, name="x", schedule_kind="once", run_at=1700000000000)
    assert compute_next(t) == 1700000000000


@pytest.mark.asyncio
async def test_create_task_with_delay_seconds():
    """delay_seconds → 自动转 once。'X 分钟后提醒' 的核心。"""
    from app.core.db import AsyncSessionLocal, init_models
    from app.models import Agent, Tenant
    from app.services.schedule_service import create_task

    await init_models()
    async with AsyncSessionLocal() as db:
        ten = Tenant(name="S", slug="s-aiops")
        db.add(ten); await db.flush()
        ag = Agent(tenant_id=ten.id, owner_id=1, name="助手", slug="asst", type="agent", system_prompt="")
        db.add(ag); await db.flush()
        before = int(time.time() * 1000)
        t = await create_task(db, tenant_id=ten.id, owner_id=1, data={
            "name": "提醒喝水", "agent_id": ag.id, "target_type": "prompt",
            "prompt": "提醒用户喝水", "delay_seconds": 60,
        })
        await db.commit()
        assert t.schedule_kind == "once"
        assert t.run_at and t.run_at > before
        assert 55_000 <= (t.run_at - before) <= 65_000


@pytest.mark.asyncio
async def test_create_delete_kb_via_tool():
    from app.agents.tools.base import ToolContext
    from app.agents.tools.ops_tools import CreateKbTool, DeleteKbTool
    from app.core.db import AsyncSessionLocal, init_models
    from app.services.permission import PrincipalSet

    await init_models()
    async with AsyncSessionLocal() as db:
        ps = PrincipalSet(user_id=1, tenant_id=1)
        ctx = ToolContext(db=db, ps=ps, tenant_id=1, user_id=1)
        r = await CreateKbTool().execute({"name": "AI建库", "visibility": "internal"}, ctx)
        assert not r.is_error and r.data.get("id")
        kid = r.data["id"]
        r2 = await DeleteKbTool().execute({"kb_id": kid}, ctx)
        assert not r2.is_error


@pytest.mark.asyncio
async def test_create_user_tool():
    from app.agents.tools.base import ToolContext
    from app.agents.tools.ops_tools import CreateUserTool
    from app.core.db import AsyncSessionLocal, init_models
    from app.services.permission import PrincipalSet

    await init_models()
    async with AsyncSessionLocal() as db:
        ps = PrincipalSet(user_id=1, tenant_id=1)
        ctx = ToolContext(db=db, ps=ps, tenant_id=1, user_id=1)
        r = await CreateUserTool().execute(
            {"username": f"aiu_{int(time.time())}", "password": "secret123", "display_name": "AI建用户"}, ctx)
        assert not r.is_error


def test_api_key_has_key_prefix_field():
    """create_api_key 工具依赖 key_prefix 字段（防字段名漂移）。"""
    from app.models import ApiKey

    cols = ApiKey.__table__.columns
    assert "key_prefix" in cols and "key_hash" in cols
