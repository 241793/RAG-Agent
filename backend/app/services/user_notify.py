"""用户相关通知：注册申请、审核结果等，通知管理员/申请人。

站内消息用 create_inapp 在**当前业务 session** 写入（随事务提交），
避免 dispatch 的独立 session 在注册事务尚未提交时读不到新用户。
外渠（邮件/Webhook/企微）通过 dispatch 异步派发，失败不影响主流程。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.notifiers.base import NotificationMessage

logger = get_logger("user_notify")


async def _admin_ids(db: AsyncSession, tenant_id: int) -> list[int]:
    """该租户所有启用的管理员 id（含租户超管）。"""
    from app.models import User

    rows = (
        await db.execute(
            select(User.id).where(
                User.tenant_id == tenant_id,
                User.is_admin.is_(True),
                User.status == "active",
            )
        )
    ).all()
    return [r[0] for r in rows]


async def notify_admins_registration(
    db: AsyncSession, *, tenant_id: int, user, reason: str | None = None
) -> None:
    """新用户提交注册申请 → 通知所有管理员（站内 + 外渠）。

    失败静默（不让通知问题阻断注册）。
    """
    try:
        from app.notifiers.drivers.inapp import create_inapp
        from app.notifiers.registry import dispatch

        name = getattr(user, "display_name", None) or user.username
        dept = ""
        if getattr(user, "department_id", None):
            from app.models import Department

            d = await db.get(Department, user.department_id)
            if d:
                dept = d.name
        lines = [
            f"用户名：{user.username}",
            f"姓名：{name}",
        ]
        if user.email:
            lines.append(f"邮箱：{user.email}")
        if dept:
            lines.append(f"申请部门：{dept}")
        if reason:
            lines.append(f"申请理由：{reason}")
        lines.append("请前往「用户管理」审核。")
        body = "\n".join(lines)

        admin_ids = await _admin_ids(db, tenant_id)
        # 站内消息：直接落当前 session（随注册事务一起提交）
        for aid in admin_ids:
            await create_inapp(db, tenant_id=tenant_id, user_id=aid, msg=NotificationMessage(
                title=f"新用户注册申请：{name}",
                body=body, level="info", kind="system",
                link="/admin/users", ref_type="user", ref_id=user.id,
                meta={"username": user.username, "email": user.email, "department": dept or None},
            ))
        # 外渠（邮件/Webhook/企微等）：按各渠道订阅的 kind 过滤自动分发。
        # skip_inapp：站内消息已在上面写好，避免重复写入。
        if admin_ids:
            await dispatch(db, tenant_id=tenant_id, msg=NotificationMessage(
                title=f"新用户注册申请：{name}",
                body=body, level="info", kind="user_register",
                link="/admin/users", ref_type="user", ref_id=user.id,
                meta={"username": user.username},
            ), user_id=admin_ids[0], skip_inapp=True)
    except Exception:  # noqa: BLE001
        logger.exception("notify_admins_registration_failed", user_id=getattr(user, "id", None))


async def notify_user_review_result(
    db: AsyncSession, *, tenant_id: int, user, approved: bool, operator_name: str = ""
) -> None:
    """审核结果通知申请人（站内，附带账号状态说明）。失败静默。"""
    try:
        from app.notifiers.drivers.inapp import create_inapp

        name = getattr(user, "display_name", None) or user.username
        if approved:
            title = "您的注册申请已通过"
            body = f"账号「{name}」已通过审核，现在可以登录使用。"
            level = "success"
        else:
            title = "您的注册申请未通过"
            body = f"账号「{name}」的注册申请未通过，如有疑问请联系管理员。"
            level = "warning"
        await create_inapp(db, tenant_id=tenant_id, user_id=user.id, msg=NotificationMessage(
            title=title, body=body, level=level, kind="system",
            link="/login", ref_type="user", ref_id=user.id,
        ))
    except Exception:  # noqa: BLE001
        logger.exception("notify_user_review_result_failed", user_id=getattr(user, "id", None))
