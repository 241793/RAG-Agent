"""办公文档工具：模板渲染、生成文件、Markdown 表格解析。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.office_tools import OFFICE_TOOLS, OfficeDocTool, _TEMPLATES, _md_table
from app.agents.tools.registry import registry
from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Tenant, User
from app.services.permission import PrincipalSet


def test_office_tool_registered():
    t = registry.get_builtin("generate_office_doc")
    assert t is not None
    assert t.required_permission == "file:write"
    assert t.kind == "write"
    assert t in OFFICE_TOOLS or t.name == "generate_office_doc"


def test_md_table():
    out = _md_table(["事项", "负责人"], [["A", "张三"], ["B", "李四"]])
    assert "| 事项 | 负责人 |" in out
    assert "| --- | --- |" in out
    assert "| A | 张三 |" in out


def test_minutes_template():
    md = _TEMPLATES["minutes"][1]({
        "title": "项目周会", "date": "2026-01-05", "attendees": ["张三", "李四"],
        "agenda": ["进度同步", "风险讨论"],
        "decisions": ["本周完成联调"],
        "todos": [{"task": "跟进需求", "owner": "张三", "due": "周五"}],
    })
    assert "项目周会" in md and "参会人员" in md and "张三" in md
    assert "## 待办事项" in md and "| 事项 | 负责人 | 截止时间 |" in md


def test_report_template():
    md = _TEMPLATES["report"][1]({
        "kind": "周报", "author": "王五", "done": ["完成 A 模块"],
        "doing": [{"task": "B 模块", "progress": "60%", "owner": "王五"}],
        "plan": ["开始 C"], "issues": ["依赖第三方"],
    })
    assert "周报" in md and "## 已完成" in md and "完成 A 模块" in md
    assert "| 事项 | 进度 | 负责人 |" in md and "## 问题与风险" in md


def test_official_template():
    md = _TEMPLATES["official"][1]({
        "title": "关于放假的通知", "to": "全体员工", "from": "行政部",
        "body": "春节放假安排如下。", "sections": [{"heading": "放假时间", "content": "1月20日至28日"}],
        "signature": "行政部",
    })
    assert "关于放假的通知" in md and "全体员工" in md and "## 放假时间" in md


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "ofc2"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="OFC2", slug="ofc2"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "ofc2_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="ofc2_u", password_hash=hash_password("x"), is_admin=True)
            db.add(u); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "user_id": u.id}


def test_generate_office_doc_docx():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                              tenant_id=d["tenant_id"], user_id=d["user_id"])
            r = await OfficeDocTool().run({
                "template": "minutes", "format": "docx",
                "data": {"title": "测试纪要", "todos": [{"task": "X", "owner": "Y", "due": "周五"}]},
            }, ctx)
            await db.commit()
            assert not r.is_error, r.content
            assert r.data.get("artifact_id")
            assert r.data["name"].endswith(".docx")
    asyncio.new_event_loop().run_until_complete(_run())


def test_generate_office_doc_pdf():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                              tenant_id=d["tenant_id"], user_id=d["user_id"])
            r = await OfficeDocTool().run({
                "template": "report", "format": "pdf",
                "data": {"kind": "日报", "done": ["事项1"], "plan": ["事项2"]},
            }, ctx)
            await db.commit()
            assert not r.is_error
            assert r.data["name"].endswith(".pdf")
    asyncio.new_event_loop().run_until_complete(_run())


def test_generate_office_doc_bad_template():
    async def _run():
        d = await _setup()
        async with AsyncSessionLocal() as db:
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["user_id"], tenant_id=d["tenant_id"], is_admin=True),
                              tenant_id=d["tenant_id"], user_id=d["user_id"])
            r = await OfficeDocTool().run({"template": "nope", "data": {}}, ctx)
            assert r.is_error and "模板" in r.content
    asyncio.new_event_loop().run_until_complete(_run())
