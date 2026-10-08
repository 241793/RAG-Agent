"""QQ 官方机器人渠道（OpenAPI）。

- 入站：WebSocket 长连接（默认），op:10 Hello → op:2 Identify → op:0 Dispatch
- 出站：POST /v2/{groups|users}/{target}/messages（被动回复带 msg_id + msg_seq）
配置：app_id、client_secret。（webhook 模式由 api/v1/channels.py 回调端点承接，见 Ed25519 验签）
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx

from app.channels.base import InboundMessage, OutboundMessage
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

GROUP_EVENTS = ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE", "GROUP_REPLY_CREATE")
C2C_EVENTS = ("C2C_MESSAGE_CREATE", "C2C_MSG_REPLY_CREATE")
FULL_INTENTS = (1 << 30) | (1 << 12) | (1 << 25) | (1 << 26)
MSG_TYPE_TEXT = 0

# 重连退避（秒）
RECONNECT_DELAYS = [1, 2, 3, 5, 8, 10]
FAST_RECONNECT = 0.5      # 服务端要求重连 / 会话超时
AUTH_FAIL_RECONNECT = 1   # 鉴权失败（刷 token 后快速重连）
RATE_LIMIT_DELAY = 60     # 命中限流
SESSION_ALIVE_SECONDS = 30  # 上次连接超过此时长才 Resume（避免短间隔 Resume 被拒 4902）

_seq = 0


def _next_seq() -> int:
    global _seq
    _seq = (_seq + 1) % 100000
    return _seq


def _strip_mention(content: str) -> str:
    import re

    return re.sub(r"<@!?\d+>|<@![^>]*>", "", content or "").strip()


class QQBotAdapter:
    def __init__(self, *, config: dict, on_message) -> None:
        self.cfg = config or {}
        self.on_message = on_message
        self.app_id = str(self.cfg.get("app_id") or "")
        self.client_secret = str(self.cfg.get("client_secret") or "")
        if not self.app_id or not self.client_secret:
            raise ValidationError("QQ 机器人缺少 app_id/client_secret")
        self._stop = False
        self._ws = None
        self._token = ""
        self._token_expire = 0.0
        self._session_id: str | None = None
        self._last_seq = 0
        self._heartbeat_task: asyncio.Task | None = None
        self._sessions: dict[str, dict] = {}   # target_id → {msg_id,is_group}
        self._force_token = False       # 下次 Hello 前强制刷 token
        self._expect_reconnect = False  # 服务端要求重连
        self._conn_start = 0.0          # 上次连接开始时刻（判定是否 Resume）

    # ---- token ----
    async def _get_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expire - 60:
            return self._token
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(TOKEN_URL, json={"appId": self.app_id, "clientSecret": self.client_secret})
            d = r.json()
        tok = str(d.get("access_token") or "")
        if not tok:
            raise RuntimeError(f"获取 AccessToken 失败: {d}")
        self._token = tok
        self._token_expire = time.time() + int(d.get("expires_in", 7200) or 7200)
        return tok

    async def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.request(method, API_BASE + path, headers={"Authorization": f"QQBot {token}"}, json=body)
            return r.json() if r.text else {}

    # ---- 生命周期 ----
    async def connect(self) -> None:
        self._stop = False
        attempt = 0
        while not self._stop:
            self._conn_start = time.time()
            close_code = None
            try:
                close_code = await self._run_once()
                if self._stop:
                    break
                # 正常返回（服务端要求重连 / 会话超时）→ 快速重连
                delay = FAST_RECONNECT if (self._expect_reconnect or close_code in (4006, 4007, 4009)) else None
                self._expect_reconnect = False
                if delay is None:
                    delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                    attempt += 1
                else:
                    attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                if self._stop:
                    break
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                attempt += 1
            if self._stop:
                break
            await asyncio.sleep(delay)

    async def disconnect(self) -> None:
        self._stop = True
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _run_once(self) -> int | None:
        """建立一次连接并处理帧。返回 websocket 关闭码（用于重连决策）。"""
        import websockets

        gw = (await self._api("GET", "/gateway")).get("url")
        if not gw:
            raise RuntimeError("获取网关失败")
        async with websockets.connect(gw, ping_interval=None, max_size=2**23) as ws:
            self._ws = ws
            try:
                async for raw in ws:
                    if self._stop:
                        break
                    try:
                        payload = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        continue
                    await self._handle_payload(ws, payload)
            except websockets.exceptions.ConnectionClosed as e:
                return getattr(e, "code", None)
        return getattr(ws, "close_code", None)

    async def _handle_payload(self, ws, payload: dict) -> None:
        op = payload.get("op")
        d = payload.get("d")
        t = payload.get("t")
        s = payload.get("s")
        if s is not None:
            self._last_seq = s   # 每帧更新 seq，供心跳/Resume 使用

        if op == OP_HELLO:
            interval = (d or {}).get("heartbeat_interval", 30000) / 1000.0
            force = self._force_token or not self._token
            try:
                token = await self._get_token(force=force)
                self._force_token = False
            except Exception:  # noqa: BLE001
                self._force_token = True
                await ws.close()
                return
            alive = time.time() - self._conn_start
            can_resume = bool(self._session_id and self._last_seq and alive > SESSION_ALIVE_SECONDS)
            if can_resume:
                await ws.send(json.dumps({"op": OP_RESUME, "d": {
                    "token": f"QQBot {token}", "session_id": self._session_id, "seq": self._last_seq,
                }}))
            else:
                if self._session_id:
                    self._session_id = None
                    self._last_seq = 0
                await ws.send(json.dumps({"op": OP_IDENTIFY, "d": {
                    "token": f"QQBot {token}", "intents": FULL_INTENTS, "shard": [0, 1],
                }}))
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._heartbeat(ws, interval))
        elif op == OP_DISPATCH:
            if t == "READY":
                self._session_id = (d or {}).get("session_id")
            elif t == "RESUMED":
                pass
            else:
                await self._dispatch(t, d or {})
        elif op == OP_HEARTBEAT_ACK:
            pass
        elif op == OP_RECONNECT:
            self._expect_reconnect = True
            self._force_token = True
            await ws.close()
        elif op == OP_INVALID_SESSION:
            # 会话失效：清除 session，下次 Identify
            self._session_id = None
            self._last_seq = 0
            await ws.close()

    async def _heartbeat(self, ws, interval: float) -> None:
        import random

        await asyncio.sleep(interval * random.uniform(0.1, 0.5))  # 首帧抖动
        while not self._stop:
            try:
                await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._last_seq}))
            except Exception:  # noqa: BLE001
                return
            await asyncio.sleep(interval)

    async def _dispatch(self, event: str, data: dict) -> None:
        if event not in GROUP_EVENTS and event not in C2C_EVENTS:
            return
        msg = self.parse_event(event, data)
        if msg and self.on_message:
            await self.on_message(msg)

    def parse_event(self, event: str, data: dict) -> InboundMessage | None:
        is_group = event in GROUP_EVENTS
        author = data.get("author") or {}
        user_openid = str(author.get("member_openid") or author.get("user_openid") or "").strip()
        if not user_openid:
            return None
        content = str(data.get("content") or "")
        if is_group:
            content = _strip_mention(content)
        group = str(data.get("group_openid") or "") if is_group else None
        mid = str(data.get("id") or data.get("msg_id") or "")
        target = group or user_openid
        self._sessions[target] = {"msg_id": mid, "is_group": is_group}
        # 附件：QQ 机器人附件 url 直链，需带 QQBot token 头下载
        attachments: list[dict] = []
        for att in (data.get("attachments") or []):
            if not isinstance(att, dict):
                continue
            url = str(att.get("url") or "").strip()
            if not url:
                continue
            ct = str(att.get("content_type") or "").lower()
            atype = "image" if "image" in ct else "file"
            attachments.append({
                "type": atype, "name": str(att.get("filename") or atype),
                "mime": ct or "application/octet-stream", "url": url,
                "headers": {"Authorization": f"QQBot {self._token}"} if self._token else None,
                "_channel": "qqbot",
            })
        return InboundMessage(
            channel="qqbot", external_user=user_openid, content=content,
            external_group=group, is_group=is_group, message_id=mid, raw=data,
            attachments=attachments,
        )

    # ---- 发送 ----
    async def send_message(self, msg: OutboundMessage) -> bool:
        target = msg.group_id or msg.user_id
        if not target:
            return False
        is_group = bool(msg.group_id)
        sess = self._sessions.get(str(target), {})
        # QQ 官方 Bot 富媒体需额外权限且接口不稳定：有 media 时把文件名并入文本。
        content = msg.content
        if msg.media:
            names = "、".join(m.get("name") or "附件" for m in msg.media)
            content = f"{content}\n[附件] {names}" if content else f"[附件] {names}"
        body: dict = {"content": content, "msg_type": MSG_TYPE_TEXT, "msg_seq": _next_seq()}
        if sess.get("msg_id"):
            body["msg_id"] = sess["msg_id"]
        path = f"/v2/groups/{target}/messages" if is_group else f"/v2/users/{target}/messages"
        resp = await self._api("POST", path, body)
        code = int(resp.get("code", 0) or 0)
        return code == 0

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            await self._get_token()
            return ProviderHealth(ok=True, message="凭据有效", latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
