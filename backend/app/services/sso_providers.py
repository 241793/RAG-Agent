"""SSO 提供者：统一接口 + 四个平台（OIDC / 企业微信 / 钉钉 / 飞书）。

统一流程：
  build_authorize_url(config, state, redirect_uri) -> str
  exchange_and_profile(config, code, redirect_uri) -> dict   # 返回标准化的用户信息
标准化用户信息：{"subject","username","display_name","email","dept_code","groups"}
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass

import httpx

# ---- PKCE / state 工具 ----


def new_state() -> str:
    return secrets.token_urlsafe(24)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class SsoProfile:
    subject: str
    username: str
    display_name: str = ""
    email: str | None = None
    dept_code: str | None = None
    groups: list[str] | None = None


# ==================== 通用 OIDC ====================
async def oidc_authorize_url(cfg, state: str, redirect_uri: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": cfg.scopes or "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    from urllib.parse import urlencode

    return f"{cfg.authorize_url}?{urlencode(params)}"


async def oidc_exchange(cfg, code: str, redirect_uri: str, verifier: str) -> SsoProfile:
    async with httpx.AsyncClient(timeout=15) as c:
        tok = await c.post(
            cfg.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "code_verifier": verifier,
            },
        )
        tok.raise_for_status()
        data = tok.json()
    access_token = data.get("access_token")
    id_token = data.get("id_token")

    claims: dict = {}
    if id_token:
        claims = _decode_id_token_unverified(id_token)  # MVP：不验签（生产应验 JWKS）
    # 用 userinfo 补充
    if cfg.userinfo_url and access_token:
        async with httpx.AsyncClient(timeout=15) as c:
            u = await c.get(cfg.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
            if u.status_code < 400:
                claims = {**claims, **u.json()}
    return _map_claims(cfg, claims)


def _decode_id_token_unverified(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001
        return {}


# ==================== 企业微信 ====================
async def wecom_authorize_url(cfg, state: str, redirect_uri: str, verifier: str) -> str:
    from urllib.parse import quote

    return (
        "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
        f"?appid={cfg.client_id}&agentid={cfg.agent_id or ''}"
        f"&redirect_uri={quote(redirect_uri, safe='')}&state={state}"
    )


async def wecom_exchange(cfg, code: str, redirect_uri: str, verifier: str) -> SsoProfile:
    async with httpx.AsyncClient(timeout=15) as c:
        # 获取 access_token
        t = await c.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": cfg.corp_id or cfg.client_id, "corpsecret": cfg.client_secret},
        )
        t.raise_for_status()
        access_token = t.json().get("access_token")
        # code 换 userid
        u = await c.get(
            "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo",
            params={"access_token": access_token, "code": code},
        )
        u.raise_for_status()
        info = u.json()
        userid = info.get("userid") or info.get("UserId")
        # 拉用户详情
        detail = {}
        if userid:
            d = await c.get(
                "https://qyapi.weixin.qq.com/cgi-bin/user/get",
                params={"access_token": access_token, "userid": userid},
            )
            if d.status_code < 400:
                detail = d.json()
    return SsoProfile(
        subject=str(userid or info.get("openid", "")),
        username=str(userid or info.get("openid", "")),
        display_name=detail.get("name", ""),
        email=detail.get("email") or None,
        dept_code=str((detail.get("department") or [None])[0]) if detail.get("department") else None,
    )


# ==================== 钉钉 ====================
async def dingtalk_authorize_url(cfg, state: str, redirect_uri: str, verifier: str) -> str:
    from urllib.parse import quote, urlencode

    params = {
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "client_id": cfg.client_id,
        "scope": "openid",
        "state": state,
        "prompt": "consent",
    }
    return f"https://login.dingtalk.com/oauth2/auth?{urlencode(params)}"


async def dingtalk_exchange(cfg, code: str, redirect_uri: str, verifier: str) -> SsoProfile:
    async with httpx.AsyncClient(timeout=15) as c:
        tok = await c.post(
            "https://api.dingtalk.com/v1.0/oauth2/userAccessToken",
            json={
                "clientId": cfg.client_id,
                "clientSecret": cfg.client_secret,
                "code": code,
                "grantType": "authorization_code",
            },
        )
        tok.raise_for_status()
        access_token = tok.json().get("accessToken")
        u = await c.get(
            "https://api.dingtalk.com/v1.0/contact/users/me",
            headers={"x-acs-dingtalk-access-token": access_token},
        )
        u.raise_for_status()
        info = u.json()
    return SsoProfile(
        subject=str(info.get("unionId") or info.get("openId", "")),
        username=str(info.get("nick") or info.get("unionId", "")),
        display_name=info.get("nick", ""),
        email=info.get("email") or None,
    )


# ==================== 飞书 ====================
async def feishu_authorize_url(cfg, state: str, redirect_uri: str, verifier: str) -> str:
    from urllib.parse import quote

    return (
        "https://open.feishu.cn/open-apis/authen/v1/authorize"
        f"?app_id={cfg.client_id}&redirect_uri={quote(redirect_uri, safe='')}&state={state}"
    )


async def feishu_exchange(cfg, code: str, redirect_uri: str, verifier: str) -> SsoProfile:
    async with httpx.AsyncClient(timeout=15) as c:
        # app_access_token
        app = await c.post(
            "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal",
            json={"app_id": cfg.client_id, "app_secret": cfg.client_secret},
        )
        app.raise_for_status()
        app_token = app.json().get("app_access_token")
        # code 换 user_access_token
        tok = await c.post(
            "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token",
            headers={"Authorization": f"Bearer {app_token}"},
            json={"grant_type": "authorization_code", "code": code},
        )
        tok.raise_for_status()
        user_token = tok.json().get("data", {}).get("access_token")
        # 拉用户信息
        u = await c.get(
            "https://open.feishu.cn/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        u.raise_for_status()
        info = u.json().get("data", {})
    return SsoProfile(
        subject=str(info.get("union_id") or info.get("open_id", "")),
        username=str(info.get("user_id") or info.get("name", "")),
        display_name=info.get("name", ""),
        email=info.get("email") or None,
    )


# ==================== 分发 ====================
PROVIDERS = {
    "oidc": (oidc_authorize_url, oidc_exchange),
    "wecom": (wecom_authorize_url, wecom_exchange),
    "dingtalk": (dingtalk_authorize_url, dingtalk_exchange),
    "feishu": (feishu_authorize_url, feishu_exchange),
}


def _map_claims(cfg, claims: dict) -> SsoProfile:
    """按 attribute_map 把原始 claims 映射为标准 profile。"""
    am = cfg.attribute_map or {}
    if "sub" not in claims and "subject" not in claims:
        claims = {**claims}
    subject = str(claims.get(am.get("subject", "sub")) or claims.get("sub") or claims.get("openid") or "")
    username = str(claims.get(am.get("username", "preferred_username")) or claims.get("email") or subject)
    display = str(claims.get(am.get("display_name", "name")) or claims.get("name") or username)
    email = claims.get(am.get("email", "email"))
    groups = claims.get(am.get("groups", "groups"))
    if isinstance(groups, str):
        groups = [groups]
    dept = claims.get(am.get("dept_code", "department"))
    return SsoProfile(
        subject=subject or username,
        username=username,
        display_name=display,
        email=email,
        dept_code=str(dept) if dept else None,
        groups=groups,
    )


async def build_authorize_url(cfg, state: str, redirect_uri: str, verifier: str) -> str:
    fn = PROVIDERS.get(cfg.provider, (None, None))[0]
    if not fn:
        raise ValueError(f"不支持的 SSO 提供者: {cfg.provider}")
    return await fn(cfg, state, redirect_uri, verifier)


async def exchange_and_profile(cfg, code: str, redirect_uri: str, verifier: str) -> SsoProfile:
    fn = PROVIDERS.get(cfg.provider, (None, None))[1]
    if not fn:
        raise ValueError(f"不支持的 SSO 提供者: {cfg.provider}")
    return await fn(cfg, code, redirect_uri, verifier)
