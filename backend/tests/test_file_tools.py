"""文件处理工具测试：生成/转换产物 + Artifact 落库 + 跨租户拒绝 + 过期清理。"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from app.agents.tools.base import ToolContext
from app.agents.tools.file_tools import ConvertFileToTool, GenerateFileTool, ReadFileTool
from app.core.db import AsyncSessionLocal, init_models
from app.ingest.storage import get_storage
from app.models import Artifact, Tenant, User
from app.services.permission import PrincipalSet


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "ft"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="FT", slug="ft"); db.add(t); await db.flush()
        u = (await db.execute(select(User).where(User.username == "ft_u"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=t.id, username="ft_u", password_hash="x"); db.add(u); await db.flush()
        await db.commit()
        return {"tid": t.id, "uid": u.id}


async def _run():
    d = await _setup()
    ps = PrincipalSet(user_id=d["uid"], tenant_id=d["tid"])

    # 1) 生成 docx
    async with AsyncSessionLocal() as db:
        ctx = ToolContext(db=db, ps=ps, tenant_id=d["tid"], user_id=d["uid"], conversation_id=1)
        res = await GenerateFileTool().execute(
            {"filename": "报告.docx", "format": "docx", "content": "# 标题\n正文段落"}, ctx)
        assert not res.is_error, res.content
        aid = res.data["artifact_id"]
        fk = res.data["file_key"]
        assert fk.startswith(f"{d['tid']}/"), fk
        # 文件落盘
        assert get_storage().path(fk).is_file()
        # Artifact 落库
        art = await db.get(Artifact, aid)
        assert art and art.file_name == "报告.docx" and art.source == "generated"

    # 2) 生成 xlsx（rows）
    async with AsyncSessionLocal() as db:
        ctx = ToolContext(db=db, ps=ps, tenant_id=d["tid"], user_id=d["uid"])
        res = await GenerateFileTool().execute(
            {"filename": "数据.xlsx", "format": "xlsx", "rows": [["a", "b"], [1, 2]]}, ctx)
        assert not res.is_error
        assert get_storage().path(res.data["file_key"]).is_file()

    # 3) 生成 pdf
    async with AsyncSessionLocal() as db:
        ctx = ToolContext(db=db, ps=ps, tenant_id=d["tid"], user_id=d["uid"])
        res = await GenerateFileTool().execute(
            {"filename": "文档.pdf", "format": "pdf", "content": "中文内容测试"}, ctx)
        assert not res.is_error, res.content

    # 4) 跨租户读取被拒
    async with AsyncSessionLocal() as db:
        ctx = ToolContext(db=db, ps=ps, tenant_id=d["tid"], user_id=d["uid"])
        res = await ReadFileTool().run({"file_key": "99999/abc.txt"}, ctx)
        assert res.is_error and "无权" in res.content, res.content

    # 5) xlsx→csv 转换
    async with AsyncSessionLocal() as db:
        ctx = ToolContext(db=db, ps=ps, tenant_id=d["tid"], user_id=d["uid"])
        gen = await GenerateFileTool().execute(
            {"filename": "src.xlsx", "format": "xlsx", "rows": [["x", "y"], [3, 4]]}, ctx)
        src_key = gen.data["file_key"]
        conv = await ConvertFileToTool().execute({"file_key": src_key, "target_ext": "csv"}, ctx)
        assert not conv.is_error, conv.content
        content = get_storage().read(conv.data["file_key"]).decode("utf-8")
        assert "x" in content and "3" in content, content

    # 6) 过期清理
    async with AsyncSessionLocal() as db:
        db.add(Artifact(tenant_id=d["tid"], user_id=d["uid"], file_key=f"{d['tid']}/expired.bin",
                        file_name="expired.bin", size=1, source="generated",
                        expires_at=int(time.time() * 1000) - 1000))
        await db.commit()
    from app.tasks.artifact_tasks import cleanup_expired_artifacts

    async with AsyncSessionLocal() as db:
        n = await cleanup_expired_artifacts(db)
        assert n >= 1, n
    print("OK file_tools")


def test_file_tools():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_content_disposition_handles_non_ascii():
    """文件名含中文时 Content-Disposition 必须可 latin-1 编码（否则响应 500）。"""
    from app.core.http_utils import content_disposition

    for name in ("pelican-bicycle.html", "鹈鹕骑自行车.html", "合并导出-3篇.pdf", 'a b"c.txt'):
        val = content_disposition(name, inline=True)
        val.encode("latin-1")  # 复现 starlette 头部编码，不能再抛 UnicodeEncodeError
        assert val.startswith("inline;")
        assert "filename*=UTF-8''" in val
    assert content_disposition("中文.docx").startswith("attachment;")
