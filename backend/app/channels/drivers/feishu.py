"""飞书渠道（官方 lark-oapi 长连接 + HTTP 发送）。

- 入站：lark-oapi ws.Client 长连接，注册 im.message.receive_v1 事件（require lark_oapi）
- 出站：调用 im.v1.message.create（HTTP，用 tenant_access_token）
配置：app_id、app_secret。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx

from app.channels.base import InboundMessage, OutboundMessage
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

OPEN_API = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{OPEN_API}/auth/v3/tenant_access_token/internal"


class FeishuAdapter:
    def __init__(self, *, config: dict, on_message) -> None:
        self.cfg = config or {}
        self.on_message = on_message
        self.app_id = str(self.cfg.get("app_id") or "")
        self.app_secret = str(self.cfg.get("app_secret") or "")
        if not self.app_id or not self.app_secret:
            raise ValidationError("飞书缺少 app_id/app_secret")
        self._stop = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._token = ""
        self._token_expire = 0.0

    # ---- 出站 ----
    async def _tenant_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expire - 60:
            return self._token
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(TOKEN_URL, json={"app_id": self.app_id, "app_secret": self.app_secret})
            d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {d}")
        self._token = d["tenant_access_token"]
        self._token_expire = time.time() + int(d.get("expire", 7200) or 7200)
        return self._token

    async def send_message(self, msg: OutboundMessage) -> bool:
        target = msg.group_id or msg.user_id
        if not target or (not msg.content and not msg.media):
            return False
        receive_id_type = "open_id" if str(target).startswith("ou_") else "chat_id"
        token = await self._tenant_token()
        ok = True
        # 先发媒体（图片/文件）
        for m in (msg.media or []):
            try:
                ok = await self._send_media(str(target), receive_id_type, token, m) and ok
            except Exception:  # noqa: BLE001
                ok = False
        # 再发文本（有则发）
        if msg.content:
            body = {"receive_id": str(target), "msg_type": "text",
                    "content": json.dumps({"text": msg.content}, ensure_ascii=False)}
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{OPEN_API}/im/v1/messages",
                                 params={"receive_id_type": receive_id_type},
                                 headers={"Authorization": f"Bearer {token}"}, json=body)
            ok = (r.json().get("code") == 0) and ok
        return ok

    async def _send_media(self, target: str, receive_id_type: str, token: str, m: dict) -> bool:
        """上传图片/文件 → 发消息。图片走 /im/v1/images，文件走 /im/v1/files。"""
        data = m.get("data")
        if not data:
            return False
        name = m.get("name") or "file"
        is_image = m.get("type") == "image" or (m.get("mime") or "").startswith("image/")
        async with httpx.AsyncClient(timeout=60) as c:
            if is_image:
                r = await c.post(f"{OPEN_API}/im/v1/images",
                                 headers={"Authorization": f"Bearer {token}"},
                                 data={"image_type": "message"},
                                 files={"image": (name, data, m.get("mime") or "image/png")})
                key = (r.json().get("data") or {}).get("image_key")
                if not key:
                    return False
                body = {"receive_id": target, "msg_type": "image",
                        "content": json.dumps({"image_key": key})}
            else:
                # file_type 用 stream（通用二进制流）
                r = await c.post(f"{OPEN_API}/im/v1/files",
                                 headers={"Authorization": f"Bearer {token}"},
                                 data={"file_type": "stream", "file_name": name},
                                 files={"file": (name, data, m.get("mime") or "application/octet-stream")})
                key = (r.json().get("data") or {}).get("file_key")
                if not key:
                    return False
                body = {"receive_id": target, "msg_type": "file",
                        "content": json.dumps({"file_key": key})}
            r2 = await c.post(f"{OPEN_API}/im/v1/messages",
                              params={"receive_id_type": receive_id_type},
                              headers={"Authorization": f"Bearer {token}"}, json=body)
        return r2.json().get("code") == 0

    # ---- 入站 ----
    async def connect(self) -> None:
        try:
            import lark_oapi as lark  # noqa: F401
        except Exception as e:  # noqa: BLE001
            raise ValidationError(f"飞书长连接需要安装 lark-oapi：pip install lark-oapi（{e}）") from e

        self._stop = False
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._run_stream, daemon=True)
        self._thread.start()
        while not self._stop:
            await asyncio.sleep(1)

    def _run_stream(self) -> None:
        import lark_oapi as lark

        # SDK 内部可能调用 asyncio.run；在已有 loop 的线程里需 nest_asyncio 兜底
        try:
            import nest_asyncio

            nest_asyncio.apply()
        except Exception:  # noqa: BLE001
            pass

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_event)
            .build()
        )
        ws = lark.ws.Client(self.app_id, self.app_secret, event_handler=handler,
                            log_level=lark.LogLevel.INFO)
        ws.start()  # 阻塞，直到断开

    def _on_event(self, data) -> None:
        msg = self._parse_lark_event(data)
        if msg and self.on_message and self._loop:
            asyncio.run_coroutine_threadsafe(self.on_message(msg), self._loop)

    def _parse_lark_event(self, data) -> InboundMessage | None:
        """直接从 lark-oapi 事件对象读取字段（避免 JSON 往返）。

        注意：chat_type/chat_id 在 message 上（P2ImMessageReceiveV1Data 只有 sender+message），
        对 event.* 的取值仅作兼容兜底。
        """
        try:
            event = data.event
            message = event.message
            sender = event.sender
            chat_type = (getattr(message, "chat_type", "") or getattr(event, "chat_type", "") or "")
            chat_id = (getattr(message, "chat_id", "") or getattr(event, "chat_id", "") or "")
            user_id = (sender.sender_id.open_id if sender and sender.sender_id else "") or ""
        except Exception:  # noqa: BLE001
            return None
        if not user_id:
            return None
        is_group = chat_type == "group"
        mtype = getattr(message, "message_type", "text") or "text"
        content_raw = getattr(message, "content", "") or "{}"
        mid = str(getattr(message, "message_id", "") or "")
        attachments: list[dict] = []
        if mtype == "text":
            try:
                content = json.loads(content_raw).get("text", "")
            except Exception:  # noqa: BLE001
                content = str(content_raw)
        elif mtype == "image":
            content = "[图片]"
            try:
                key = json.loads(content_raw).get("image_key")
            except Exception:  # noqa: BLE001
                key = None
            if key:
                attachments.append({
                    "type": "image", "name": f"{key}.png", "mime": "image/png",
                    "key": key, "feishu_kind": "image", "message_id": mid,
                    "_feishu_cfg": {"app_id": self.app_id, "app_secret": self.app_secret},
                    "_channel": "feishu",
                })
        elif mtype == "file":
            content = "[文件]"
            try:
                obj = json.loads(content_raw)
                key = obj.get("file_key")
                fname = obj.get("file_name") or "file"
            except Exception:  # noqa: BLE001
                key, fname = None, "file"
            if key:
                attachments.append({
                    "type": "file", "name": fname, "mime": "application/octet-stream",
                    "key": key, "feishu_kind": "file", "message_id": mid,
                    "_feishu_cfg": {"app_id": self.app_id, "app_secret": self.app_secret},
                    "_channel": "feishu",
                })
        else:
            content = str(content_raw)
        return InboundMessage(
            channel="feishu", external_user=user_id, content=content,
            external_group=chat_id if (is_group and chat_id) else None,
            is_group=is_group, message_id=mid,
            raw={"chat_type": chat_type}, attachments=attachments,
        )

    def parse_event(self, raw: dict) -> InboundMessage | None:
        """供测试用：从 dict 解析（结构与飞书回调 JSON 一致）。"""
        event = raw.get("event", {}) or {}
        message = event.get("message", {}) or {}
        sender = event.get("sender", {}) or {}
        # chat_type/chat_id 在 message 上；event.* 仅兼容兜底
        chat_type = str(message.get("chat_type") or event.get("chat_type") or "")
        chat_id = str(message.get("chat_id") or event.get("chat_id") or "")
        user_id = str((sender.get("sender_id") or {}).get("open_id") or "")
        if not user_id:
            return None
        is_group = chat_type == "group"
        mtype = str(message.get("message_type") or "text")
        content_raw = message.get("content") or "{}"
        mid = str(message.get("message_id") or "")
        attachments: list[dict] = []
        _cfg = {"app_id": self.app_id, "app_secret": self.app_secret}
        if mtype == "text":
            try:
                content = json.loads(content_raw).get("text", "")
            except Exception:  # noqa: BLE001
                content = str(content_raw)
        elif mtype == "image":
            content = "[图片]"
            try:
                key = json.loads(content_raw).get("image_key")
            except Exception:  # noqa: BLE001
                key = None
            if key:
                attachments.append({
                    "type": "image", "name": f"{key}.png", "mime": "image/png",
                    "key": key, "feishu_kind": "image", "message_id": mid,
                    "_feishu_cfg": _cfg, "_channel": "feishu",
                })
        elif mtype == "file":
            content = "[文件]"
            try:
                obj = json.loads(content_raw)
                key = obj.get("file_key")
                fname = obj.get("file_name") or "file"
            except Exception:  # noqa: BLE001
                key, fname = None, "file"
            if key:
                attachments.append({
                    "type": "file", "name": fname, "mime": "application/octet-stream",
                    "key": key, "feishu_kind": "file", "message_id": mid,
                    "_feishu_cfg": _cfg, "_channel": "feishu",
                })
        else:
            content = str(content_raw)
        return InboundMessage(
            channel="feishu", external_user=user_id, content=content,
            external_group=chat_id if (is_group and chat_id) else None,
            is_group=is_group, message_id=mid, raw=raw, attachments=attachments,
        )

    async def disconnect(self) -> None:
        self._stop = True

    async def health(self) -> ProviderHealth:
        t0 = time.time()
        try:
            await self._tenant_token()
            return ProviderHealth(ok=True, message="凭据有效", latency_ms=int((time.time() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            return ProviderHealth(ok=False, message=str(e)[:300], latency_ms=int((time.time() - t0) * 1000))
