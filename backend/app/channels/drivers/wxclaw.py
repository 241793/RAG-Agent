"""微信（iLink wxclaw，非官方）渠道：HTTP 轮询 + context_token 回复。

api 地址固定为 https://ilinkai.weixin.qq.com（见 wxclaw_login.FIXED_API_URL），
token 通过渠道页"扫码登录"获取（get_bot_qrcode → get_qrcode_status）。
注意：非官方协议，上游可能变更；已隔离为独立驱动，失败不影响其它渠道。
用户发消息后仅 24 小时内可回复（官方限制）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time

import httpx

from app.channels.base import InboundMessage, OutboundMessage
from app.core.errors import ValidationError
from app.providers.base import ProviderHealth

GET_UPDATES_PATH = "ilink/bot/getupdates"
SEND_MESSAGE_PATH = "ilink/bot/sendmessage"
CREATE_UPLOAD_PATH = "ilink/bot/getuploadurl"
CONTEXT_TTL = 24 * 3600


class WxClawAdapter:
    def __init__(self, *, config: dict, on_message) -> None:
        from app.channels.wxclaw_login import FIXED_API_URL

        self.cfg = config or {}
        self.on_message = on_message
        # api_url 固定（不对外配置）；仅当配置显式给了非空值时才用（兼容自建/测试）
        self.api_url = str(self.cfg.get("api_url") or FIXED_API_URL).rstrip("/")
        self.token = str(self.cfg.get("token") or "")
        self.auth_type = str(self.cfg.get("authorization_type") or "ilink_bot_token")
        self.x_uin = str(self.cfg.get("x_wechat_uin") or "")
        self.poll_interval = float(self.cfg.get("poll_interval_sec") or 2)
        if not self.token:
            raise ValidationError("微信渠道缺少 token（请在渠道页扫码登录或用其它方式获取）")
        self._stop = False
        self._cursor = ""
        self._context: dict[str, dict] = {}   # user_id → {token, ts}
        self._seen: dict[str, float] = {}

    def _headers(self) -> dict:
        uin = self.x_uin or base64.b64encode(str(int.from_bytes(os.urandom(4), "big")).encode()).decode()
        auth = self.token if self.token.lower().startswith("bearer ") else f"Bearer {self.token}"
        return {"Content-Type": "application/json", "AuthorizationType": self.auth_type,
                "Authorization": auth, "X-WECHAT-UIN": uin}

    def _url(self, path: str) -> str:
        return f"{self.api_url}/{path.lstrip('/')}"

    async def connect(self) -> None:
        self._stop = False
        from app.core.logging import get_logger

        log = get_logger("channel")
        async with httpx.AsyncClient(timeout=25) as c:
            while not self._stop:
                try:
                    await self._poll_once(c)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.warning("wxclaw_poll_error", err=str(e)[:200])
                    await asyncio.sleep(2)
                await asyncio.sleep(max(0.2, self.poll_interval))

    async def disconnect(self) -> None:
        self._stop = True

    async def _poll_once(self, c: httpx.AsyncClient) -> None:
        payload = {"get_updates_buf": self._cursor or "", "base_info": {"channel_version": "1.0.3"}}
        r = await c.post(self._url(GET_UPDATES_PATH), headers=self._headers(), json=payload)
        if r.status_code != 200:
            from app.core.logging import get_logger

            get_logger("channel").warning("wxclaw_poll_http", status=r.status_code, body=(r.text or "")[:200])
            return
        data = r.json()
        if int(data.get("ret", 0) or 0) != 0:
            from app.core.logging import get_logger

            get_logger("channel").warning("wxclaw_poll_ret", ret=data.get("ret"), msg=str(data.get("msg"))[:150])
            return
        for raw in (data.get("msgs") or []):
            await self._handle(raw)
        new_cursor = str(data.get("get_updates_buf") or data.get("next_get_updates_buf") or self._cursor)
        if new_cursor:
            self._cursor = new_cursor

    async def _handle(self, raw: dict) -> None:
        if not isinstance(raw, dict):
            return
        key = f"{raw.get('message_id')}|{raw.get('client_id')}|{raw.get('from_user_id')}"
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if now - v < 600}
        if key in self._seen:
            return
        self._seen[key] = now
        msg = self.parse_message(raw)
        if msg and self.on_message:
            await self.on_message(msg)

    def parse_message(self, raw: dict) -> InboundMessage | None:
        if int(raw.get("message_type", 0) or 0) not in (1, 2, 3, 4, 5):
            return None
        user_id = str(raw.get("from_user_id") or raw.get("to_user_id") or "")
        if not user_id:
            return None
        token = str(raw.get("context_token") or "")
        if token:
            self._context[user_id] = {"token": token, "ts": time.time()}
        chunks: list[str] = []
        attachments: list[dict] = []
        for item in (raw.get("item_list") or []):
            if not isinstance(item, dict):
                continue
            itype = int(item.get("type", 0) or 0)
            if itype == 1:
                txt = str(((item.get("text_item") or {}).get("text")) or "").strip()
                if txt:
                    chunks.append(txt)
            elif itype == 2:
                # 图片：取 CDN 下载信息（url 优先直链，否则 encrypt_query_param + aes_key）
                img = item.get("image_item") or {}
                media = img.get("media") or {}
                url = str(img.get("cdn_big_img_url") or media.get("full_url")
                          or img.get("full_url") or "").strip()
                aes_key = str(media.get("aes_key") or img.get("aes_key") or "").strip()
                eqp = str(media.get("encrypt_query_param") or "").strip()
                attachments.append({
                    "type": "image", "name": "image.png", "mime": "image/png",
                    "url": url or None, "encrypt_query_param": eqp or None,
                    "aes_key": aes_key or None, "_channel": "wxclaw",
                })
                chunks.append("[图片]")
            elif itype == 3:
                vt = item.get("voice_item") or item.get("voice_text") or {}
                t = str(vt.get("text") or "").strip()
                if t:
                    chunks.append(t)
                else:
                    chunks.append("[语音]")
            elif itype == 4:
                fi = item.get("file_item") or {}
                fname = str(fi.get("filename") or fi.get("file_name") or "文件").strip()
                media = fi.get("media") or {}
                eqp = str(media.get("encrypt_query_param") or "").strip()
                aes_key = str(media.get("aes_key") or "").strip()
                attachments.append({
                    "type": "file", "name": fname, "mime": "application/octet-stream",
                    "encrypt_query_param": eqp or None, "aes_key": aes_key or None, "_channel": "wxclaw",
                })
                chunks.append(f"[文件: {fname}]")
            elif itype == 5:
                chunks.append("[视频]")
        return InboundMessage(
            channel="wxclaw", external_user=user_id, content="\n".join(chunks).strip(),
            message_id=str(raw.get("message_id") or ""), raw=raw, attachments=attachments,
        )

    async def send_message(self, msg: OutboundMessage) -> bool:
        from app.core.logging import get_logger

        log = get_logger("channel")
        target = msg.user_id or msg.group_id
        if not target:
            log.warning("wxclaw_send_skip", reason="no_target", target=target)
            return False
        entry = self._context.get(str(target))
        if not entry or time.time() - entry["ts"] > CONTEXT_TTL:
            log.warning("wxclaw_send_skip", reason="no_context_token", target=str(target),
                        has_entry=bool(entry), age=round(time.time() - entry["ts"], 1) if entry else None)
            return False
        ok = True
        # 发送媒体（图片/文件）——逐条；失败不影响文本
        for m in (msg.media or []):
            try:
                sent = await self._send_media(target, entry["token"], m)
                ok = ok and sent
            except Exception as e:  # noqa: BLE001
                log.warning("wxclaw_media_send_error", err=str(e)[:200])
                ok = False
        # 发送文本
        if msg.content:
            ok = await self._send_text(target, entry["token"], msg.content) and ok
        return ok

    async def _send_text(self, target: str, ctx_token: str, content: str) -> bool:
        from app.core.logging import get_logger

        log = get_logger("channel")
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": str(target),
                "client_id": f"rag_{int(time.time() * 1000)}_{os.urandom(4).hex()}",
                "message_type": 2,
                "message_state": 2,
                "create_time_ms": int(time.time() * 1000),
                "update_time_ms": int(time.time() * 1000),
                "context_token": ctx_token,
                "item_list": [{"type": 1, "text_item": {"text": content}}],
            },
            "base_info": {"channel_version": "1.0.3"},
        }
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(self._url(SEND_MESSAGE_PATH), headers=self._headers(), json=payload)
            body = ""
            try:
                body = r.text[:300]
            except Exception:  # noqa: BLE001
                pass
            ok = r.status_code == 200 and int(r.json().get("ret", 0) or 0) == 0
            if not ok:
                log.warning("wxclaw_send_failed", target=str(target), status=r.status_code, body=body)
            else:
                log.info("wxclaw_send_ok", target=str(target))
            return ok
        except Exception as e:  # noqa: BLE001
            log.warning("wxclaw_send_error", target=str(target), err=str(e)[:200])
            return False

    async def _send_media(self, target: str, ctx_token: str, m: dict) -> bool:
        """发送图片/文件：AES 加密 → getuploadurl → CDN 上传 → 发消息带 cdn_media。"""
        from app.channels import media as medi
        from app.core.logging import get_logger

        log = get_logger("channel")
        data = m.get("data")
        if not data and m.get("path"):
            try:
                with open(m["path"], "rb") as f:
                    data = f.read()
            except Exception:  # noqa: BLE001
                return False
        if not data:
            return False
        media_type = 1 if m.get("type") == "image" else 3  # 1=图片 3=文件
        raw_md5 = medi.md5_hex(data)
        key = os.urandom(16)
        enc = medi.aes_ecb_encrypt(data, key)
        aes_key_hex = key.hex()
        aes_key_b64 = base64.b64encode(aes_key_hex.encode("ascii")).decode("ascii")
        file_key = os.urandom(16).hex()
        # 1) 取上传地址（getuploadurl 需带鉴权头）
        up = await self._post_json(CREATE_UPLOAD_PATH, {
            "filekey": file_key, "media_type": media_type, "to_user_id": str(target),
            "rawsize": len(data), "rawfilemd5": raw_md5, "filesize": len(enc),
            "no_need_thumb": True, "aeskey": aes_key_hex,
            "base_info": {"channel_version": "1.0.3"},
        })
        udata = up.get("data") or {}
        full = str(udata.get("upload_full_url") or "").strip()
        param = str(udata.get("upload_param") or "").strip()
        if full.startswith("http"):
            cdn_url = full
        elif param:
            from urllib.parse import quote
            cdn_url = f"{medi.WXCLAW_CDN_BASE}/upload?encrypted_query_param={quote(param, safe='')}&filekey={quote(file_key, safe='')}"
        else:
            log.warning("wxclaw_upload_no_url", resp=str(up)[:200])
            return False
        # 2) CDN 上传
        eqp = ""
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(cdn_url, content=enc, headers={"Content-Type": "application/octet-stream"})
                if r.status_code in (200, 201, 204):
                    eqp = r.headers.get("x-encrypted-param", "")
        except Exception as e:  # noqa: BLE001
            log.warning("wxclaw_cdn_upload_error", err=str(e)[:150])
            return False
        cdn_media: dict = {"aes_key": aes_key_b64, "encrypt_type": 1}
        if eqp:
            cdn_media["encrypt_query_param"] = eqp
        item = {"type": 2 if media_type == 1 else 4, "media": cdn_media}
        if media_type == 3:
            item["file_item"] = {"filename": m.get("name") or "file"}
        # 3) 发媒体消息
        payload = {
            "msg": {
                "from_user_id": "", "to_user_id": str(target),
                "client_id": f"rag_{int(time.time() * 1000)}_{os.urandom(4).hex()}",
                "message_type": 2, "message_state": 2,
                "create_time_ms": int(time.time() * 1000), "update_time_ms": int(time.time() * 1000),
                "context_token": ctx_token, "item_list": [item],
            },
            "base_info": {"channel_version": "1.0.3"},
        }
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(self._url(SEND_MESSAGE_PATH), headers=self._headers(), json=payload)
            return r.status_code == 200 and int(r.json().get("ret", 0) or 0) == 0
        except Exception:  # noqa: BLE001
            return False

    async def _post_json(self, path: str, body: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(self._url(path), headers=self._headers(), json=body)
            return r.json() if r.text else {}
        except Exception:  # noqa: BLE001
            return {}

    async def health(self) -> ProviderHealth:
        if not self.token:
            return ProviderHealth(ok=False, message="缺少 token（请扫码登录）", latency_ms=0)
        return ProviderHealth(ok=True, message="配置完整（非官方协议，发送依赖用户 24h 内互动）", latency_ms=0)
