"""渠道服务：配置加解密、外部身份解析（首次自动建虚拟用户）、会话映射。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.core.errors import NotFoundError
from app.models import Channel, ChannelUser, Conversation, User
from app.services.permission import PrincipalSet, user_principal

_SECRET_KEYS = ("secret", "token", "password", "app_secret", "encoding_aes_key", "client_secret")


def encrypt_config(cfg: dict | None, existing: dict | None = None) -> dict | None:
    """加密渠道配置中的敏感字段；已加密则保留，空值沿用旧密文。"""
    if not cfg:
        return cfg
    out = dict(cfg)
    for k in list(out.keys()):
        if not any(s in k.lower() for s in _SECRET_KEYS):
            continue
        v = out[k]
        if isinstance(v, str) and v.startswith("enc:"):
            continue
        if (v is None or v == "") and existing and existing.get(k):
            out[k] = existing[k]  # 未改动，沿用旧值
        elif v:
            out[k] = encrypt(v)
    return out


def decrypt_config(cfg: dict | None) -> dict:
    if not cfg:
        return {}
    out = dict(cfg)
    for k in list(out.keys()):
        if any(s in k.lower() for s in _SECRET_KEYS) and isinstance(out[k], str) and out[k].startswith("enc:"):
            out[k] = decrypt(out[k])
    return out


def mask_config(cfg: dict | None) -> dict:
    """脱敏回显：敏感字段显示为是否已设置。"""
    if not cfg:
        return {}
    out = dict(cfg)
    for k in list(out.keys()):
        if any(s in k.lower() for s in _SECRET_KEYS) and out[k]:
            out[k] = "••••"
            out[f"{k}_set"] = True
    return out


async def get_channel(db: AsyncSession, channel_id: int, tenant_id: int) -> Channel:
    ch = await db.get(Channel, channel_id)
    if not ch or ch.tenant_id != tenant_id or ch.status == "deleted":
        raise NotFoundError("渠道不存在")
    return ch


async def resolve_channel_user(
    db: AsyncSession, *, channel: Channel, external_id: str, display_name: str | None = None
) -> tuple[ChannelUser, User, User | None]:
    """解析外部身份 → 本地虚拟用户。首次自动建档（只读权限）。

    返回 (ChannelUser, 虚拟User, bound内部账号|None)。绑定后，权限判定用 bound 账号的真实身份。
    """
    cu = (
        await db.execute(
            select(ChannelUser).where(
                ChannelUser.channel == channel.kind, ChannelUser.external_id == external_id
            )
        )
    ).scalar_one_or_none()

    if cu:
        user = await db.get(User, cu.user_id)
        # 懒回填：渠道虚拟用户一律标记为 external（历史数据在 user_type 字段新增前建的为 NULL）
        if user and getattr(user, "user_type", None) != "external":
            user.user_type = "external"
        if user and user.status == "active":
            # 回填会话/名称
            if display_name and not cu.display_name:
                cu.display_name = display_name
            return cu, user, await _bound_user(db, cu)
        # 用户被禁用：仍返回（上层拒绝）
        if user:
            return cu, user, await _bound_user(db, cu)

    # 首次：建虚拟用户 + 绑定
    tenant_id = channel.default_tenant_id or channel.tenant_id
    import hashlib
    import secrets

    uname = f"{channel.kind}_{external_id[:40]}"
    # 避免用户名冲突
    exist_u = (await db.execute(select(User).where(User.tenant_id == tenant_id, User.username == uname))).scalar_one_or_none()
    if exist_u:
        user = exist_u
    else:
        # 随机不可登录密码哈希
        pwd_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        user = User(
            tenant_id=tenant_id, username=uname, password_hash=pwd_hash,
            display_name=display_name or f"{channel.kind}用户", is_admin=False, status="active",
            user_type="external",
        )
        db.add(user)
        await db.flush()

    cu = ChannelUser(
        tenant_id=tenant_id, channel=channel.kind, external_id=external_id,
        user_id=user.id, display_name=display_name,
        default_kb_ids=channel.default_kb_ids or None,
    )
    db.add(cu)
    await db.flush()
    return cu, user, None


async def _bound_user(db: AsyncSession, cu: ChannelUser) -> User | None:
    """取 ChannelUser 绑定的内部账号（活跃且非外部）。"""
    if not cu.bound_user_id:
        return None
    u = await db.get(User, cu.bound_user_id)
    if u and u.status == "active" and getattr(u, "user_type", "internal") != "external":
        return u
    return None


async def ensure_conversation(db: AsyncSession, *, cu: ChannelUser, channel: Channel) -> Conversation:
    """确保该渠道用户有一个会话（多轮上下文）。/new 时置空重建。"""
    if cu.conversation_id:
        conv = await db.get(Conversation, cu.conversation_id)
        if conv:
            return conv
    conv = Conversation(
        tenant_id=cu.tenant_id, user_id=cu.user_id,
        title=f"[{channel.kind}] {cu.display_name or cu.external_id[:12]}",
        kb_ids=(cu.default_kb_ids or channel.default_kb_ids or []),
        settings={"channel": channel.kind, "external_id": cu.external_id, "channel_id": channel.id},
    )
    db.add(conv)
    await db.flush()
    cu.conversation_id = conv.id
    return conv


def principal_of(user: User, bound_user: User | None = None) -> PrincipalSet:
    """渠道用户的 PrincipalSet。

    - 已绑定内部账号（bound_user）：用其真实身份（管理员=全权；保留角色/部门/组）。
    - 未绑定：外部客户只读（is_admin=False, is_external=True）。
    """
    if bound_user is not None:
        return PrincipalSet(
            user_id=bound_user.id, tenant_id=bound_user.tenant_id,
            is_admin=bool(bound_user.is_admin),
            is_external=(getattr(bound_user, "user_type", "internal") == "external"),
        )
    return PrincipalSet(user_id=user.id, tenant_id=user.tenant_id, is_admin=False,
                        is_external=(getattr(user, "user_type", "internal") == "external"))


__all__ = [
    "encrypt_config", "decrypt_config", "mask_config", "get_channel",
    "resolve_channel_user", "ensure_conversation", "principal_of", "user_principal",
]
