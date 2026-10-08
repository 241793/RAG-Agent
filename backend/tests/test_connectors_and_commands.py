"""本轮新增：飞书表格/Google Sheets 连接器、渠道 /ticket+/record 指令、表格分析工具。"""
from __future__ import annotations

import asyncio
import csv
import io

import pytest

from app.connectors.drivers.feishu_sheet import _cell_text
from app.core.errors import ValidationError


# ---- 飞书表格连接器 ----
def test_feishu_cell_text():
    assert _cell_text("abc") == "abc"
    assert _cell_text(123) == "123"
    assert _cell_text({"text": "hi"}) == "hi"
    assert _cell_text({"link": "http://x"}) == "http://x"
    assert _cell_text([{"text": "a"}, {"text": "b"}]) == "a b"
    assert _cell_text(None) == ""


def test_feishu_config_validation():
    from app.connectors.drivers.feishu_sheet import FeishuSheetConnector

    with pytest.raises(ValidationError):
        FeishuSheetConnector(kb_id=1, config={})
    with pytest.raises(ValidationError):
        FeishuSheetConnector(kb_id=1, config={"app_id": "a", "app_secret": "s", "base_token": "b"})  # bitable 缺 table_id
    # sheet 模式缺 sheet_id
    with pytest.raises(ValidationError):
        FeishuSheetConnector(kb_id=1, config={"app_id": "a", "app_secret": "s", "base_token": "b", "mode": "sheet"})


def test_google_config_validation():
    from app.connectors.drivers.google_sheet import GoogleSheetConnector

    with pytest.raises(ValidationError):
        GoogleSheetConnector(kb_id=1, config={})


def test_registry_builds_new_connectors():
    from app.connectors.drivers.feishu_sheet import FeishuSheetConnector
    from app.connectors.drivers.google_sheet import GoogleSheetConnector
    from app.connectors.registry import build_connector

    c1 = build_connector("feishu_sheet", {"app_id": "a", "app_secret": "s", "base_token": "b", "table_id": "t"})
    assert isinstance(c1, FeishuSheetConnector)
    c2 = build_connector("google_sheet", {"spreadsheet_id": "sid"})
    assert isinstance(c2, GoogleSheetConnector)


# ---- 渠道指令 ----
def test_new_commands_registered():
    from app.channels.commands import COMMANDS, HELP_TEXT

    assert "ticket" in COMMANDS and "record" in COMMANDS
    assert "ticket" in HELP_TEXT and "record" in HELP_TEXT


def test_ticket_command_list_empty():
    from app.channels.commands import cmd_ticket

    async def _run():
        from app.core.db import AsyncSessionLocal, init_models
        from app.models import Channel, ChannelUser, Tenant, User
        from app.core.security import hash_password

        await init_models()
        async with AsyncSessionLocal() as db:
            t = (await db.execute(__import__("sqlalchemy").select(Tenant).where(Tenant.slug == "cmdc"))).scalar_one_or_none()
            if not t:
                t = Tenant(name="C", slug="cmdc"); db.add(t); await db.flush()
            u = (await db.execute(__import__("sqlalchemy").select(User).where(User.username == "cmdc_u"))).scalar_one_or_none()
            if not u:
                u = User(tenant_id=t.id, username="cmdc_u", password_hash=hash_password("x")); db.add(u); await db.flush()
            ch = (await db.execute(__import__("sqlalchemy").select(Channel).where(Channel.name == "cmdc_ch"))).scalar_one_or_none()
            if not ch:
                ch = Channel(tenant_id=t.id, kind="wework", name="cmdc_ch", enabled=True); db.add(ch); await db.flush()
            cu = ChannelUser(tenant_id=t.id, channel="wework", external_id="cuid1", user_id=u.id)
            db.add(cu); await db.commit()

            from app.channels.commands import CommandContext
            ctx = CommandContext(db=db, channel=ch, channel_user=cu, user=u, ps=None)
            r = await cmd_ticket(ctx, ["list"])
            assert "还没有工单" in r or "没有工单" in r
            # 建单
            r2 = await cmd_ticket(ctx, ["退款", "问题"])
            await db.commit()
            assert "已创建工单" in r2
    asyncio.new_event_loop().run_until_complete(_run())


# ---- 表格分析工具 ----
def test_analyze_table_registered():
    from app.agents.tools.registry import registry

    t = registry.get_builtin("analyze_table")
    assert t is not None and t.required_permission == "file:read"


def test_analyze_table_agg(tmp_path, monkeypatch):
    from openpyxl import Workbook

    from app.agents.tools.base import ToolContext
    from app.agents.tools.file_tools import AnalyzeTableTool
    from app.services.permission import PrincipalSet

    wb = Workbook(); ws = wb.active
    ws.append(["类别", "金额", "客户"])
    for r in [["A", 100, "张三"], ["A", 200, "李四"], ["B", 50, "王五"]]:
        ws.append(r)
    p = tmp_path / "t.xlsx"; wb.save(str(p))

    class FakeStorage:
        def path(self, fk): return p

    import app.agents.tools.file_tools as ft
    monkeypatch.setattr(ft, "get_storage", lambda: FakeStorage())
    ctx = ToolContext(db=None, ps=PrincipalSet(user_id=1, tenant_id=1), tenant_id=1, user_id=1)

    async def _run(args):
        return await AnalyzeTableTool().run(args, ctx)

    loop = asyncio.new_event_loop()
    preview = loop.run_until_complete(_run({"file_key": "1/t.xlsx"}))
    assert "3 行" in preview.content and "类别" in preview.content
    total = loop.run_until_complete(_run({"file_key": "1/t.xlsx", "column": "金额", "agg": "sum"}))
    assert "350" in total.content
    grouped = loop.run_until_complete(_run({"file_key": "1/t.xlsx", "column": "金额", "agg": "group", "group_by": "类别"}))
    assert "A: 合计 300" in grouped.content and "B: 合计 50" in grouped.content
    avg = loop.run_until_complete(_run({"file_key": "1/t.xlsx", "column": "金额", "agg": "avg"}))
    assert "116.667" in avg.content
