"""能力感知测试：功能清单、权限过滤、注入、查权限工具。"""
from __future__ import annotations

import pytest


def test_platform_features_nonempty():
    from app.agents.capabilities import PLATFORM_FEATURES

    names = [f[0] for f in PLATFORM_FEATURES]
    for must in ("智能问答", "知识库", "智能体", "工作流", "定时任务", "外部渠道", "成员与权限"):
        assert must in names, f"缺少功能：{must}"


def test_current_capabilities_admin_all_allowed():
    from app.agents.capabilities import current_capabilities

    caps = current_capabilities(set(), is_admin=True)
    assert all(c["allowed"] for c in caps)


def test_current_capabilities_filtered_by_perms():
    from app.agents.capabilities import current_capabilities

    caps = current_capabilities({"chat:use"}, is_admin=False)
    chat = next(c for c in caps if c["name"] == "智能问答")
    kb = next(c for c in caps if c["name"] == "知识库")
    assert chat["allowed"] is True
    assert kb["allowed"] is False


@pytest.mark.asyncio
async def test_check_permission_brief_query():
    from app.agents.capabilities import check_permission_brief

    # 无权：明确提示缺什么权限
    brief = await check_permission_brief({"chat:use"}, False, query="成员")
    assert "成员" in brief and "无权限" in brief

    # 有权
    brief2 = await check_permission_brief({"chat:use", "user:read"}, False, query="成员")
    assert "可用" in brief2


@pytest.mark.asyncio
async def test_check_permission_brief_full():
    from app.agents.capabilities import check_permission_brief

    b = await check_permission_brief(set(), True)
    assert "管理员" in b
    b2 = await check_permission_brief({"chat:use"}, False)
    assert "智能问答" in b2


@pytest.mark.asyncio
async def test_build_capability_brief_contains_sections():
    from app.agents.capabilities import build_capability_brief

    brief = await build_capability_brief(None, perms={"chat:use"}, is_admin=False)
    assert "[平台能力]" in brief
    assert "[当前账号]" in brief
    assert "智能问答" in brief
    # 无权功能应标注需什么权限
    assert "kb:read" in brief


def test_check_my_capabilities_tool_registered():
    from app.agents.tools.registry import registry

    names = [t.name for t in registry.all_builtin()]
    assert "check_my_capabilities" in names
    t = registry.get_builtin("check_my_capabilities")
    assert getattr(t, "required_permission", "__x__") is None  # 全员可用


def test_notifications_permission_fixed():
    """notifications 不应再用不存在的 chat:read 权限码。"""
    import inspect

    from app.api.v1 import notifications

    src = inspect.getsource(notifications)
    assert 'require_permission("chat:read")' not in src
    assert 'require_permission("chat:use")' in src
