"""SSO 单测：state/PKCE 生成、claims 映射、各 provider 的 authorize URL 构造。

不依赖真实 IdP；exchange 需网络的路径不在此测。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.sso_providers import (
    PROVIDERS,
    _map_claims,
    build_authorize_url,
    new_state,
    pkce_pair,
)


def _cfg(**kw):
    base = dict(
        provider="oidc", client_id="cid", client_secret="sec", scopes="openid profile email",
        authorize_url="https://idp.example.com/authorize", agent_id=None, corp_id=None,
        attribute_map=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_pkce_pair():
    v, c = pkce_pair()
    assert len(v) > 20 and len(c) > 20 and v != c


def test_new_state_unique():
    assert new_state() != new_state()


def test_map_claims_default():
    cfg = _cfg()
    p = _map_claims(cfg, {"sub": "u1", "preferred_username": "alice", "email": "a@x.com", "name": "Alice"})
    assert p.subject == "u1"
    assert p.username == "alice"
    assert p.display_name == "Alice"
    assert p.email == "a@x.com"


def test_map_claims_custom_attribute_map():
    cfg = _cfg(attribute_map={"subject": "oid", "username": "email", "display_name": "cn"})
    p = _map_claims(cfg, {"oid": "123", "email": "b@x.com", "cn": "Bob"})
    assert p.subject == "123"
    assert p.username == "b@x.com"
    assert p.display_name == "Bob"


def test_map_claims_groups_string_to_list():
    cfg = _cfg()
    p = _map_claims(cfg, {"sub": "u", "groups": "admins"})
    assert p.groups == ["admins"]


@pytest.mark.asyncio
async def test_oidc_authorize_url():
    cfg = _cfg(provider="oidc")
    url = await build_authorize_url(cfg, "st", "http://localhost/cb", "ver")
    assert url.startswith("https://idp.example.com/authorize?")
    assert "client_id=cid" in url and "state=st" in url
    assert "code_challenge_method=S256" in url


@pytest.mark.asyncio
async def test_wecom_authorize_url():
    cfg = _cfg(provider="wecom", client_id="corpid", agent_id="1000002")
    url = await build_authorize_url(cfg, "st", "http://localhost/cb", "ver")
    assert "open.work.weixin.qq.com" in url
    assert "appid=corpid" in url and "agentid=1000002" in url


@pytest.mark.asyncio
async def test_dingtalk_authorize_url():
    cfg = _cfg(provider="dingtalk")
    url = await build_authorize_url(cfg, "st", "http://localhost/cb", "ver")
    assert "login.dingtalk.com" in url and "client_id=cid" in url


@pytest.mark.asyncio
async def test_feishu_authorize_url():
    cfg = _cfg(provider="feishu", client_id="cli_x")
    url = await build_authorize_url(cfg, "st", "http://localhost/cb", "ver")
    assert "open.feishu.cn" in url and "app_id=cli_x" in url


def test_all_providers_registered():
    for name in ("oidc", "wecom", "dingtalk", "feishu"):
        assert name in PROVIDERS
        assert PROVIDERS[name][0] is not None and PROVIDERS[name][1] is not None
