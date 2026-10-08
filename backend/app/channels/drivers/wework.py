"""企业微信智能机器人渠道（长连接）。

- 入站：wss://openws.work.weixin.qq.com，连接后发 aibot_subscribe，收 aibot_msg_callback
- 出站：同连接发 aibot_send_msg（markdown）
配置：bot_id、secret、ws_url（默认官方地址）。
注：企微智能机器人仅支持被动回复/主动推送文本，不支持主动发图片。
"""
from __future__ import annotations

import asyncio
import json

from app.channels.base import InboundMessage, OutboundMessage
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

WSS_URL = "wss://openws.work.weixin.qq.com"


class WeWorkAdapter:
    def __init__(self, *, config: dict, on_message) -> None:
        self.cfg = config or {}
        self.on_message = on_message
        self.bot_id = str(self.cfg.get("bot_id") or "")
        self.secret = str(self.cfg.get("secret") or "")
        self.ws_url = str(self.cfg.get("ws_url") or WSS_URL)
        if not self.bot_id or not self.secret:
            raise ValidationError("企业微信缺少 bot_id/secret")
        self._stop = False
        self._ws = None
        self._req_ids: dict[str, str] = {}   # chat_id → 最近一次消息的 req_id（用于被动回复）

    async def connect(self) -> None:
        import websockets

        self._stop = False
        while not self._stop:
            try:
                async with websockets.connect(self.ws_url, ping_interval=None, max_size=2**23) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({
                        "cmd": "aibot_subscribe",
                        "body": {"bot_id": self.bot_id, "secret": self.secret},
                    }))
                    # 应用层心跳：连的是 ping_interval=None，需自建 ping 保活
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            if self._stop:
                                break
                            try:
                                frame = json.loads(raw)
                            except Exception:  # noqa: BLE001
                                continue
                            await self._handle(frame)
                    finally:
                        hb.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            if not self._stop:
                await asyncio.sleep(5)

    async def _heartbeat(self, ws) -> None:
        while not self._stop:
            await asyncio.sleep(30)
            try:
                pong = await ws.ping()
                await asyncio.wait_for(pong, timeout=10)
            except Exception:  # noqa: BLE001
                return

    async def disconnect(self) -> None:
        self._stop = True
        if self._ws:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _handle(self, frame: dict) -> None:
        cmd = frame.get("cmd")
        if cmd == "aibot_subscribe_ack":
            body = frame.get("body") or {}
            errcode = body.get("errcode", 0)
            if errcode:
                from app.core.logging import get_logger

                get_logger("channel").warning(
                    "wework_subscribe_failed", errcode=errcode,
                    errmsg=body.get("errmsg", ""), bot_id=self.bot_id,
                )
            return
        if cmd != "aibot_msg_callback":
            return
        req_id = (frame.get("headers") or {}).get("req_id", "")
        body = frame.get("body") or {}
        msg = self.parse_message(body, req_id)
        if msg and self.on_message:
            await self.on_message(msg)

    def parse_message(self, body: dict, req_id: str = "") -> InboundMessage | None:
        from_info = body.get("from") or {}
        user_id = str(from_info.get("userid") or "")
        if not user_id:
            return None
        msgtype = body.get("msgtype", "text")
        attachments: list[dict] = []
        if msgtype == "text":
            content = str((body.get("text") or {}).get("content") or "").strip()
        elif msgtype == "image":
            content = "[图片]"
            mediaid = (body.get("image") or {}).get("mediaid")
            if mediaid:
                attachments.append({
                    "type": "image", "name": f"{mediaid}.png", "mime": "image/png",
                    "mediaid": mediaid, "_channel": "wework",
                })
        elif msgtype == "voice":
            content = "[语音]"
        elif msgtype == "file":
            fi = body.get("file") or {}
            fname = fi.get("filename") or "file"
            content = f"[文件: {fname}]"
            mediaid = fi.get("mediaid")
            if mediaid:
                attachments.append({
                    "type": "file", "name": fname, "mime": "application/octet-stream",
                    "mediaid": mediaid, "aes_key": fi.get("aeskey") or None, "_channel": "wework",
                })
        else:
            content = str((body.get("text") or {}).get("content") or "").strip()
        chat_type = body.get("chattype", "single")
        chat_id = str(body.get("chatid") or "")
        group = chat_id if chat_type == "group" else None
        target = group or user_id
        if req_id:
            self._req_ids[str(target)] = req_id
        return InboundMessage(
            channel="wework", external_user=user_id, content=content,
            external_group=group, is_group=bool(group),
            message_id=str(body.get("msgid") or ""), raw=body, attachments=attachments,
        )

    async def send_message(self, msg: OutboundMessage) -> bool:
        target = msg.group_id or msg.user_id
        if not target or not self._ws:
            return False
        # 企微智能机器人仅支持文本/被动回复，不支持主动发图片/文件：
        # 有 media 时把文件名并入文本，客户可在系统会话中查看/下载。
        content = msg.content
        if msg.media:
            names = "、".join(m.get("name") or "附件" for m in msg.media)
            content = f"{content}\n[附件] {names}" if content else f"[附件] {names}"
        try:
            if self._req_ids.get(str(target)):
                # 被动回复：aibot_respond_msg + stream（分 start/end 两帧）
                return await self._respond_stream(self._req_ids[str(target)], content)
            # 主动推送：aibot_send_msg，chat_type 按目标判定（1=单聊 2=群聊）
            import uuid
            chat_type = 2 if (str(target).startswith("@") or len(str(target)) > 20) else 1
            frame = {
                "cmd": "aibot_send_msg",
                "headers": {"req_id": f"send_{uuid.uuid4().hex[:8]}"},
                "body": {"chatid": str(target), "chat_type": chat_type,
                         "msgtype": "markdown", "markdown": {"content": content}},
            }
            await self._ws.send(json.dumps(frame))
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _respond_stream(self, req_id: str, content: str) -> bool:
        import uuid

        stream_id = f"stream_{uuid.uuid4().hex[:8]}"
        try:
            await self._ws.send(json.dumps({
                "cmd": "aibot_respond_msg", "headers": {"req_id": req_id},
                "body": {"msgtype": "stream", "stream": {"id": stream_id, "finish": False, "content": content}},
            }))
            await self._ws.send(json.dumps({
                "cmd": "aibot_respond_msg", "headers": {"req_id": req_id},
                "body": {"msgtype": "stream", "stream": {"id": stream_id, "finish": True, "content": content}},
            }))
            return True
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> ProviderHealth:
        ok = bool(self.bot_id and self.secret)
        return ProviderHealth(ok=ok, message="配置完整" if ok else "缺少 bot_id/secret", latency_ms=0)
