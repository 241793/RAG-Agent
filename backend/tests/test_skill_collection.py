"""技能集合（多技能仓库整体导入 + 目录按需加载）测试。

不依赖真实网络：用内存构造的 zip。每个用例用唯一内容避免与其它用例/历史数据去重冲突。
"""
from __future__ import annotations

import asyncio
import io
import uuid
import zipfile

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.core.security import hash_password
from app.models import Skill, SkillPackage, Tenant, User
from app.services.permission import PrincipalSet


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "collection"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="COLLECTION", slug="collection"); db.add(t); await db.flush()
        admin = (await db.execute(select(User).where(User.username == "col_admin"))).scalar_one_or_none()
        if not admin:
            admin = User(tenant_id=t.id, username="col_admin", password_hash=hash_password("x"),
                         is_admin=True, display_name="管理员", user_type="internal")
            db.add(admin); await db.flush()
        await db.commit()
        return {"tenant_id": t.id, "admin": admin.id}


def _sample_zip(tag: str = "") -> bytes:
    # tag 使每个用例内容唯一，避免 content_hash 去重串扰
    return _make_zip({
        "60s-skills-main/skills/data-query/SKILL.md":
            f"---\nname: data-query\ndescription: 数据查询（油价/汇率）{tag}\n---\n调用 /v2/fuel-price 查油价",
        "60s-skills-main/skills/data-query/scripts/run.py": "print(1)\n",
        "60s-skills-main/skills/weather-query/SKILL.md":
            f"---\nname: weather-query\ndescription: 天气查询{tag}\n---\n天气正文",
        "60s-skills-main/README.md": "readme",
    })


async def _cleanup(db, skill_ids: list[int], pkg_ids: list[int]) -> None:
    """在同一个 session/loop 内清理（不新开事件循环）。"""
    from app.services.skill_pack_service import remove_pack_dir

    for sid in skill_ids:
        sk = await db.get(Skill, sid)
        if sk:
            await db.delete(sk)
    await db.flush()
    for pid in pkg_ids:
        pkg = await db.get(SkillPackage, pid)
        if pkg:
            remove_pack_dir(pkg.pack_dir)
            await db.delete(pkg)
    await db.commit()


def test_import_collection_creates_parent_and_children():
    async def _run():
        d = await _setup()
        from app.services.skill_pack_service import import_collection_from_upload

        async with AsyncSessionLocal() as db:
            r = await import_collection_from_upload(
                db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                filename="60s.zip", data=_sample_zip("A"),
            )
            await db.commit()
            assert r["collection"] is True
            assert r["count"] == 2
            parent = await db.get(Skill, r["skill_id"])
            assert parent.kind == "collection"
            assert parent.package_id == r["package_id"]
            children = (await db.execute(
                select(Skill).where(Skill.parent_id == parent.id)
            )).scalars().all()
            assert len(children) == 2
            assert {c.name for c in children} == {"data-query", "weather-query"}
            for c in children:
                assert c.package_id == r["package_id"], "子技能共享父的包"
                assert c.body_md, "子技能应有正文"
            dq = next(c for c in children if c.name == "data-query")
            assert "fuel-price" in (dq.body_md or "")
            assert dq.collection_subpath == "skills/data-query"
            pkg = await db.get(SkillPackage, r["package_id"])
            assert any(s["path"].startswith("skills/data-query/") for s in (pkg.entry_scripts or []))
            await _cleanup(db, [parent.id] + [c.id for c in children], [r["package_id"]])
    asyncio.new_event_loop().run_until_complete(_run())


def test_import_collection_dedup():
    async def _run():
        d = await _setup()
        from app.services.skill_pack_service import import_collection_from_upload

        z = _sample_zip("DEDUP")
        async with AsyncSessionLocal() as db:
            r1 = await import_collection_from_upload(db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                                                     filename="a.zip", data=z)
            await db.commit()
            r2 = await import_collection_from_upload(db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                                                     filename="a.zip", data=z)
            await db.commit()
            assert r2.get("duplicate") is True
            assert r2.get("existing_skill_id") == r1["skill_id"]
            await _cleanup(db, [r1["skill_id"]] + [c["id"] for c in r1["children"]], [r1["package_id"]])
    asyncio.new_event_loop().run_until_complete(_run())


def test_collection_injects_directory_not_body():
    async def _run():
        d = await _setup()
        from app.services.skill_pack_service import import_collection_from_upload
        from app.agents.runner import _render_skill_prompt

        async with AsyncSessionLocal() as db:
            r = await import_collection_from_upload(db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                                                    filename="60s.zip", data=_sample_zip("INJ"))
            await db.commit()
            parent = await db.get(Skill, r["skill_id"])
            block = await _render_skill_prompt(db, [parent], {})
            assert "技能集合" in block
            assert "data-query" in block and "weather-query" in block
            assert "fuel-price" not in block, "目录块不应含子技能正文"
            assert "load_skill" in block
            await _cleanup(db, [parent.id] + [c["id"] for c in r["children"]], [r["package_id"]])
    asyncio.new_event_loop().run_until_complete(_run())


def test_load_skill_lists_and_loads():
    async def _run():
        d = await _setup()
        from app.services.skill_pack_service import import_collection_from_upload
        from app.agents.tools.builtin import LoadSkillTool
        from app.agents.tools.base import ToolContext

        async with AsyncSessionLocal() as db:
            r = await import_collection_from_upload(db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                                                    filename="60s.zip", data=_sample_zip("LOAD"))
            await db.commit()
            tool = LoadSkillTool()
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=d["admin"], tenant_id=d["tenant_id"], is_admin=True),
                              tenant_id=d["tenant_id"], user_id=d["admin"])
            r1 = await tool.run({"parent_id": r["skill_id"]}, ctx)
            assert "data-query" in r1.content and "weather-query" in r1.content
            dq_id = next(c["id"] for c in r["children"] if c["name"] == "data-query")
            r2 = await tool.run({"skill_id": dq_id}, ctx)
            assert "fuel-price" in r2.content
            r3 = await tool.run({}, ctx)
            assert r3.is_error
            await _cleanup(db, [r["skill_id"]] + [c["id"] for c in r["children"]], [r["package_id"]])
    asyncio.new_event_loop().run_until_complete(_run())


def test_load_skill_denies_cross_tenant():
    async def _run():
        d = await _setup()
        from app.services.skill_pack_service import import_collection_from_upload
        from app.agents.tools.builtin import LoadSkillTool
        from app.agents.tools.base import ToolContext

        async with AsyncSessionLocal() as db:
            r = await import_collection_from_upload(db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                                                    filename="60s.zip", data=_sample_zip("XTEN"))
            await db.commit()
            tool = LoadSkillTool()
            ctx = ToolContext(db=db, ps=PrincipalSet(user_id=99999, tenant_id=99999, is_admin=True),
                              tenant_id=99999, user_id=99999)
            dq_id = next(c["id"] for c in r["children"] if c["name"] == "data-query")
            r2 = await tool.run({"skill_id": dq_id}, ctx)
            assert r2.is_error
            await _cleanup(db, [r["skill_id"]] + [c["id"] for c in r["children"]], [r["package_id"]])
    asyncio.new_event_loop().run_until_complete(_run())


def test_resolve_tools_autoloads_load_skill_for_collection():
    async def _run():
        d = await _setup()
        from app.services.skill_pack_service import import_collection_from_upload
        from app.agents.tools.registry import resolve_tools

        async with AsyncSessionLocal() as db:
            r = await import_collection_from_upload(db, tenant_id=d["tenant_id"], owner_id=d["admin"],
                                                    filename="60s.zip", data=_sample_zip("RES"))
            await db.commit()
            tools = await resolve_tools(db, tool_config={"builtin": {}}, skill_ids=[r["skill_id"]],
                                        tenant_id=d["tenant_id"], perms={"*"})
            assert "load_skill" in {t.name for t in tools}
            await _cleanup(db, [r["skill_id"]] + [c["id"] for c in r["children"]], [r["package_id"]])
    asyncio.new_event_loop().run_until_complete(_run())
