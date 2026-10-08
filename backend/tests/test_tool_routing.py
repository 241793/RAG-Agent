"""工具按需装配（tool routing）测试：find_tools 过滤、候选池、react 动态启用、能力摘要按需。

全部本地（mock LLM / 无真实网络）。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.builtin import FindToolsTool
from app.agents.tools.registry import registry, resolve_admin_pool, resolve_tools, to_openai_schema
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Tenant, User
from app.services.permission import PrincipalSet


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "routing"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="ROUTING", slug="routing"); db.add(t); await db.flush()
        admin = (await db.execute(select(User).where(User.username == "routing_admin"))).scalar_one_or_none()
        if not admin:
            admin = User(tenant_id=t.id, username="routing_admin", password_hash=hash_password("x"),
                         is_admin=True, display_name="管理员", user_type="internal")
            db.add(admin); await db.flush()
        viewer = (await db.execute(select(User).where(User.username == "routing_viewer"))).scalar_one_or_none()
        if not viewer:
            viewer = User(tenant_id=t.id, username="routing_viewer", password_hash=hash_password("x"),
                          is_admin=False, display_name="只读", user_type="internal")
            db.add(viewer); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "admin": admin.id, "viewer": viewer.id}


# ---------------- 核心常驻装配 ----------------
def test_core_only_toolset_drops_admin_tools():
    """核心装配（只 builtin）应远小于全量；find_tools 在核心集内，admin 工具不在。"""
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            from app.middleware.auth_dep import get_user_permission_codes
            admin = await db.get(User, d["admin"])
            perms = await get_user_permission_codes(db, admin)

            cfg = {"builtin": {}}
            for t in registry.all_builtin():
                cfg["builtin"][t.name] = {"enabled": True}
            core = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=d["tenant_id"], perms=perms)
            core_names = {t.name for t in core}
            assert "find_tools" in core_names
            assert "knowledge_retrieval" in core_names
            assert "create_scheduled_task" not in core_names  # admin 工具未下发

            full = await resolve_tools(db, tool_config={"builtin": cfg["builtin"], "admin": {"enabled": True}},
                                       skill_ids=[], tenant_id=d["tenant_id"], perms=perms)
            assert len(core) < len(full) / 3, "核心集应远小于全量"
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- find_tools ----------------
def test_find_tools_admin_matches():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            tool = FindToolsTool()
            ps = PrincipalSet(user_id=d["admin"], tenant_id=d["tenant_id"], is_admin=True)
            ctx = ToolContext(db=db, ps=ps, tenant_id=d["tenant_id"], user_id=d["admin"])
            r = await tool.run({"query": "创建定时任务"}, ctx)
            assert not r.is_error
            assert "create_scheduled_task" in (r.data or {}).get("enable_tools", [])
    asyncio.new_event_loop().run_until_complete(_run())


def test_find_tools_denies_unauthorized_tools():
    """非管理员查管理工具：不应返回其无权调用的工具。"""
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            tool = FindToolsTool()
            ps = PrincipalSet(user_id=d["viewer"], tenant_id=d["tenant_id"], is_admin=False)
            ctx = ToolContext(db=db, ps=ps, tenant_id=d["tenant_id"], user_id=d["viewer"])
            r = await tool.run({"query": "创建定时任务 删除用户"}, ctx)
            enabled = (r.data or {}).get("enable_tools", [])
            # viewer 无 schedule:edit / user:manage，不应出现这些工具
            assert "create_scheduled_task" not in enabled
            assert "delete_user" not in enabled
    asyncio.new_event_loop().run_until_complete(_run())


def test_find_tools_empty_query():
    async def _run():
        tool = FindToolsTool()
        r = await tool.run({"query": ""}, ToolContext(db=None, ps=None, tenant_id=1, user_id=1))
        assert r.is_error
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- 候选池 ----------------
def test_resolve_admin_pool_perms():
    admin_pool = resolve_admin_pool(perms={"*"}, is_external=False)
    assert len(admin_pool) > 50
    assert any(getattr(t, "kind", "read") == "write" for t in admin_pool.values())

    ext_pool = resolve_admin_pool(perms={"*"}, is_external=True)
    assert ext_pool, "外部客户仍应有只读管理工具"
    assert all(getattr(t, "kind", "read") == "read" for t in ext_pool.values()), "外部客户不得有写工具"

    viewer_pool = resolve_admin_pool(perms=set(), is_external=False)
    assert viewer_pool == {}, "无权限用户候选池应为空"


# ---------------- react 动态启用 ----------------
class _FakeChunk:
    def __init__(self, delta="", tool_calls=None, finish=False, usage=None):
        self.delta = delta
        self.reasoning = None
        self.tool_calls = tool_calls
        self.usage = usage
        self.finish = finish


class _ScriptedLLM:
    """按轮次返回脚本化响应：第 1 轮调 find_tools，第 2 轮调被启用工具，第 3 轮收尾。"""

    def __init__(self, turns):
        self.turns = turns
        self.seen_tools = []

    async def chat(self, messages, *, model, stream=True, temperature=0.3, tools=None):
        self.seen_tools.append({t["function"]["name"] for t in (tools or [])})
        turn = self.turns.pop(0) if self.turns else {"text": "完成"}
        async def _gen():
            if turn.get("tool"):
                from app.providers.base import ToolCallDelta
                yield _FakeChunk(delta="", tool_calls=[ToolCallDelta(index=0, id="c1",
                                name=turn["tool"], arguments_delta=turn.get("args", "{}"))])
            else:
                yield _FakeChunk(delta=turn.get("text", ""))
            yield _FakeChunk(finish=True)
        return _gen()


class _FakeRM:
    model_name = "fake"
    config_id = 1


def test_react_dynamic_enable_adds_tools_next_turn():
    """第 1 轮 find_tools → 第 2 轮的 openai_tools 应含被启用工具。"""
    async def _run():
        d = await _setup()
        from app.agents.react import run_react_loop

        async with AsyncSessionLocal() as db:
            from app.middleware.auth_dep import get_user_permission_codes
            admin = await db.get(User, d["admin"])
            perms = await get_user_permission_codes(db, admin)
            ps = PrincipalSet(user_id=d["admin"], tenant_id=d["tenant_id"], is_admin=True)

            cfg = {"builtin": {}}
            for t in registry.all_builtin():
                cfg["builtin"][t.name] = {"enabled": True}
            core = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=d["tenant_id"], perms=perms)
            pool = resolve_admin_pool(perms=perms, is_external=False)
            assert "create_scheduled_task" in pool

            llm = _ScriptedLLM([
                {"tool": "find_tools", "args": '{"query":"创建定时任务"}'},
                {"tool": "create_scheduled_task", "args": '{"name":"测试","schedule":"0 8 * * *","target_type":"prompt","prompt":"提醒"}'},
                {"text": "已创建"},
            ])
            events = []
            async for evt in run_react_loop(
                db=db, ps=ps, perms=perms, llm=llm, rm=_FakeRM(),
                messages=[], tools=core, dynamic_tools=pool,
                allow_auto_write=True,  # 免确认，直执行
            ):
                events.append(evt)

            # 第 1 轮的 schema 不含 create_scheduled_task；第 2 轮应含
            assert "create_scheduled_task" not in llm.seen_tools[0], "初始不应下发管理工具"
            assert "create_scheduled_task" in llm.seen_tools[1], "find_tools 后下一轮应启用"
            names = [e.get("name") for e in events if e.get("type") == "tool_call"]
            assert "find_tools" in names and "create_scheduled_task" in names
    asyncio.new_event_loop().run_until_complete(_run())


def test_react_dynamic_enable_denies_unauthorized():
    """未授权用户：即便模型幻觉出管理工具名，也无法被启用/执行。"""
    async def _run():
        d = await _setup()
        from app.agents.react import run_react_loop

        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["viewer"], tenant_id=d["tenant_id"], is_admin=False)
            # viewer 候选池为空（无管理权限）
            pool = resolve_admin_pool(perms=set(), is_external=False)
            assert pool == {}
            cfg = {"builtin": {}}
            for t in registry.all_builtin():
                cfg["builtin"][t.name] = {"enabled": True}
            core = await resolve_tools(db, tool_config=cfg, skill_ids=[], tenant_id=d["tenant_id"], perms=set())

            llm = _ScriptedLLM([
                {"tool": "create_scheduled_task", "args": "{}"},  # 幻觉越权工具
                {"text": "无法完成"},
            ])
            events = []
            async for evt in run_react_loop(
                db=db, ps=ps, perms=set(), llm=llm, rm=_FakeRM(),
                messages=[], tools=core, dynamic_tools=pool, allow_auto_write=True,
            ):
                events.append(evt)
            # 该工具不在 core 也不在 pool → 应报"未知工具"
            results = [e for e in events if e.get("type") == "tool_result"]
            assert any("未知工具" in (e.get("content") or "") or e.get("is_error") for e in results)
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- 能力摘要按需 ----------------
def test_is_capability_query():
    from app.agents.capabilities import is_capability_query

    assert is_capability_query("你能做什么")
    assert is_capability_query("我有哪些权限")
    assert not is_capability_query("帮我查一下油价")
    assert not is_capability_query("")


def test_capability_brief_banner_vs_full():
    """普通问题给短 banner；能力问题给完整摘要（更长）。"""
    async def _run():
        d = await _setup()
        from app.services.chat_service import _capability_brief

        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["admin"], tenant_id=d["tenant_id"], is_admin=True)
            banner = await _capability_brief(db, ps, query="帮我查油价")
            full = await _capability_brief(db, ps, query="你能做什么")
            assert len(banner) < 300, f"普通问题应给短横幅，实际 {len(banner)}"
            assert len(full) > len(banner) * 3, "能力问题应给完整摘要"
    asyncio.new_event_loop().run_until_complete(_run())


# ---------------- http_request 免确认（auto_approve）----------------
def test_http_request_auto_approve_flag():
    """http_request 应标记 auto_approve=True，但仍是 write（拦截外部客户）。"""
    from app.agents.tools.registry import registry

    h = registry.get_builtin("http_request")
    assert h.kind == "write", "仍需 write 以拦截外部客户"
    assert getattr(h, "auto_approve", False) is True, "高频工具应免确认"


def test_ordinary_write_tools_not_auto_approved():
    """其它写工具不应被误设为免确认。"""
    from app.agents.tools.registry import registry

    for name in ("generate_file", "edit_file", "create_skill"):
        t = registry.get_builtin(name) or registry.get_admin(name)
        assert t is not None
        assert getattr(t, "auto_approve", False) is False, f"{name} 不应免确认"


def test_react_auto_approve_tool_skips_hitl():
    """auto_approve 工具：即便传了 on_pending_action 也应直接执行，不挂起。"""
    async def _run():
        d = await _setup()
        from app.agents.react import run_react_loop
        from app.agents.tools.registry import registry

        async with AsyncSessionLocal() as db:
            from app.middleware.auth_dep import get_user_permission_codes
            admin = await db.get(User, d["admin"])
            perms = await get_user_permission_codes(db, admin)
            ps = PrincipalSet(user_id=d["admin"], tenant_id=d["tenant_id"], is_admin=True)

            http_tool = registry.get_builtin("http_request")
            pending_calls = []

            async def _pending(tool, tc, args):
                pending_calls.append(tool.name)
                raise AssertionError("auto_approve 工具不应触发挂起")

            # 让 http_request 打内网被 SSRF 拦截（快速失败，无需真实网络），但关键是**不挂起**
            llm = _ScriptedLLM([
                {"tool": "http_request", "args": '{"url":"http://127.0.0.1:1/x"}'},
                {"text": "结束"},
            ])
            events = []
            async for evt in run_react_loop(
                db=db, ps=ps, perms=perms, llm=llm, rm=_FakeRM(),
                messages=[], tools=[http_tool],
                on_pending_action=_pending,
            ):
                events.append(evt)
            assert pending_calls == [], "auto_approve 工具不应走 HITL"
            assert not any(e.get("type") == "pending_action" for e in events)
            assert not any(e.get("type") == "_suspended" for e in events)
            # 应产生 tool_result（执行过）
            assert any(e.get("type") == "tool_result" for e in events)
    asyncio.new_event_loop().run_until_complete(_run())


def test_react_ordinary_write_still_suspends():
    """普通写工具（非 auto_approve）仍应挂起。"""
    async def _run():
        d = await _setup()
        from app.agents.react import run_react_loop

        class _DummyWrite:
            name = "dummy_write"
            description = "测试写工具"
            parameters = {"type": "object", "properties": {}}
            required_permission = None
            kind = "write"  # 非 auto_approve

            async def run(self, args, ctx):
                from app.agents.tools.base import ToolResult
                return ToolResult(content="ok")

        class _Action:
            id = 999
            summary = "测试"
            expires_at = None

        suspended = []
        async def _pending(tool, tc, args):
            suspended.append(tool.name)
            return _Action()

        llm = _ScriptedLLM([
            {"tool": "dummy_write", "args": "{}"},
            {"text": "结束"},
        ])
        async with AsyncSessionLocal() as db:
            ps = PrincipalSet(user_id=d["admin"], tenant_id=d["tenant_id"], is_admin=True)
            events = []
            async for evt in run_react_loop(
                db=db, ps=ps, perms={"*"}, llm=llm, rm=_FakeRM(),
                messages=[], tools=[_DummyWrite()],
                on_pending_action=_pending,
            ):
                events.append(evt)
            assert suspended == ["dummy_write"], "普通写工具应挂起"
            assert any(e.get("type") == "pending_action" for e in events)
            assert any(e.get("type") == "_suspended" for e in events)
    asyncio.new_event_loop().run_until_complete(_run())
