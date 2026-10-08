"""通知渠道：config 加解密/脱敏、CRUD、notify_on 过滤逻辑。"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.models import NotifyChannel, Tenant


# ---- 加解密 / 脱敏（纯函数）----
def test_encrypt_config_roundtrip():
    from app.api.v1.notify_channels import _encrypt_config, _mask_config

    cfg = {"webhook_url": "https://x", "secret": "plain123"}
    enc = _encrypt_config(cfg)
    assert enc["secret"].startswith("enc:")
    assert enc["webhook_url"] == "https://x"  # 非敏感字段不动
    masked = _mask_config(enc)
    assert "plain123" not in masked["secret"]
    assert masked.get("secret_set") is True


def test_encrypt_config_idempotent():
    from app.api.v1.notify_channels import _encrypt_config

    once = _encrypt_config({"secret": "x"})
    twice = _encrypt_config(once)  # 已是密文不再二次加密
    assert once["secret"] == twice["secret"]


# ---- CRUD（DB 级）----
async def _setup():
    await init_models()
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == "nc"))).scalar_one_or_none()
        if not t:
            t = Tenant(name="NC", slug="nc"); db.add(t); await db.flush(); await db.commit()
        return t.id


async def _crud():
    tid = await _setup()
    from app.api.v1.notify_channels import _encrypt_config, _mask_config

    async with AsyncSessionLocal() as db:
        c = NotifyChannel(
            tenant_id=tid, kind="webhook", name="测试钩子",
            config=_encrypt_config({"url": "https://example.com/hook", "secret": "sk-abc"}),
            enabled=True,
        )
        db.add(c); await db.commit(); cid = c.id

    async with AsyncSessionLocal() as db:
        c = await db.get(NotifyChannel, cid)
        assert c.config["secret"].startswith("enc:")
        masked = _mask_config(c.config)
        assert "sk-abc" not in masked["secret"]

    # 删除
    async with AsyncSessionLocal() as db:
        c = await db.get(NotifyChannel, cid)
        await db.delete(c); await db.commit()
    async with AsyncSessionLocal() as db:
        assert await db.get(NotifyChannel, cid) is None
    print("OK notify_channel_crud")


# ---- notify_on 过滤（测真实 _notify）----
async def _notify_filter(monkeypatch):
    from app.core.db import AsyncSessionLocal as _S
    from app.models import ScheduledTask

    tid = await _setup()
    calls: list = []

    # monkeypatch registry.dispatch，捕获是否真的派发
    from app.notifiers import registry as reg

    async def _fake_dispatch(db, *, tenant_id, msg, user_id=None):
        calls.append(msg.title)
        return {}

    monkeypatch.setattr(reg, "dispatch", _fake_dispatch)

    from app.tasks.scheduler_tasks import _notify

    async with _S() as db:
        from app.core.security import hash_password
        from app.models import User

        u = (await db.execute(select(User).where(User.username == "nc_owner"))).scalar_one_or_none()
        if not u:
            u = User(tenant_id=tid, username="nc_owner", password_hash=hash_password("x"))
            db.add(u); await db.flush()

        async def _mk(mode: str) -> int:
            t = ScheduledTask(
                tenant_id=tid, owner_id=u.id, agent_id=1, name=f"t_{mode}",
                target_type="prompt", prompt="p", schedule_kind="once",
                run_at=0, notify_on=mode,
            )
            db.add(t); await db.flush()
            return t.id

        never_id = await _mk("never")
        success_id = await _mk("success")
        fail_id = await _mk("fail")
        always_id = await _mk("always")
        await db.commit()

    # never：成功/失败都不发
    await _notify(never_id, ok=True, result="r", error="")
    await _notify(never_id, ok=False, result="", error="e")
    # success：成功发、失败不发
    await _notify(success_id, ok=True, result="r", error="")
    await _notify(success_id, ok=False, result="", error="e")
    # fail：成功不发、失败发
    await _notify(fail_id, ok=True, result="r", error="")
    await _notify(fail_id, ok=False, result="", error="e")
    # always：都发
    await _notify(always_id, ok=True, result="r", error="")
    await _notify(always_id, ok=False, result="", error="e")

    titles = calls
    assert sum("t_never" in t for t in titles) == 0
    assert sum("t_success" in t for t in titles) == 1 and "执行成功" in [t for t in titles if "t_success" in t][0]
    assert sum("t_fail" in t for t in titles) == 1 and "执行失败" in [t for t in titles if "t_fail" in t][0]
    assert sum("t_always" in t for t in titles) == 2
    print("OK notify_on_filter")


def test_notify_on_filter_real(monkeypatch):
    _run_async(_notify_filter(monkeypatch))


def test_notify_codes_seeded():
    from app.services.permission_seed import PERMISSIONS

    codes = [p[0] for p in PERMISSIONS]
    assert "notify:read" in codes and "notify:manage" in codes


def test_notify_channel_endpoints_registered():
    from app.api.v1.notify_channels import router

    paths = {r.path for r in router.routes}
    assert "/notify-channels" in paths
    assert any("test" in p for p in paths)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_notify_channel_crud():
    _run_async(_crud())
