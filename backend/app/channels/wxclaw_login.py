"""微信（iLink wxclaw）扫码登录：固定地址 + 取码 + 轮询换 token。

参考实现：web_ui/api3.py（WXCLAW_FIXED_API_URL / get_bot_qrcode / get_qrcode_status）。
固定地址不对外暴露配置，避免用户误填。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

FIXED_API_URL = "https://ilinkai.weixin.qq.com"
LOGIN_QR_PATH = "ilink/bot/get_bot_qrcode"
LOGIN_CHECK_PATH = "ilink/bot/get_qrcode_status"
DEFAULT_BOT_TYPE = "3"


def normalize_url(base: str, path: str) -> str:
    b = str(base or "").strip().rstrip("/")
    p = str(path or "").strip().lstrip("/")
    return f"{b}/{p}" if p else b


def extract_login_payload(obj: Any) -> dict:
    """宽松解析扫码响应：兼容多种字段名（同参考 _wxclaw_extract_login_payload）。"""
    if not isinstance(obj, dict):
        return {}
    data = obj.get("data")
    src = data if isinstance(data, dict) else obj
    token = src.get("token") or src.get("access_token") or src.get("bot_token") or src.get("auth_token") or ""
    qr = (src.get("qr_url") or src.get("qrcode_url") or src.get("qrcode_img_content")
          or src.get("qrcodeUrl") or src.get("url") or src.get("qr")
          or src.get("qr_base64") or src.get("image") or "")
    ticket = (src.get("ticket") or src.get("uuid") or src.get("login_id")
              or src.get("qrcode") or src.get("key") or src.get("state") or "")
    status = str(src.get("status") or src.get("state") or "").strip().lower()
    bot_id = (src.get("ilink_user_id") or src.get("user_id") or src.get("myuid")
              or src.get("ilink_bot_id") or src.get("bot_id") or "")
    return {
        "token": str(token or "").strip(),
        "qr": str(qr or "").strip(),
        "ticket": str(ticket or "").strip(),
        "status": status,
        "bot_id": str(bot_id or "").strip(),
    }


async def build_display_qr(text_or_url: str) -> str:
    """把文本/URL 转成可直接显示的二维码 data URL（经外部服务，失败返回空）。"""
    raw = str(text_or_url or "").strip()
    if not raw:
        return ""
    enc = quote(raw, safe="")
    providers = [
        f"https://api.qrserver.com/v1/create-qr-code/?size=360x360&data={enc}",
        f"https://quickchart.io/qr?size=360&text={enc}",
    ]
    for u in providers:
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as c:
                r = await c.get(u)
            if r.status_code >= 400:
                continue
            if "image" not in (r.headers.get("Content-Type") or "").lower():
                continue
            if not r.content:
                continue
            import base64

            return f"data:image/png;base64,{base64.b64encode(r.content).decode('ascii')}"
        except Exception:  # noqa: BLE001
            continue
    return ""


async def fetch_login_qr(*, api_url: str | None = None, bot_type: str = DEFAULT_BOT_TYPE) -> dict:
    """调用 get_bot_qrcode 取二维码。返回 extract_login_payload 结构。"""
    url = normalize_url(api_url or FIXED_API_URL, LOGIN_QR_PATH)
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}bot_type={bot_type}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(url)
        if r.status_code >= 400:
            raise RuntimeError(f"扫码接口 HTTP {r.status_code}: {(r.text or '')[:200]}")
        return extract_login_payload(r.json())


async def check_login_status(
    ticket: str, *, api_url: str | None = None, check_path: str = LOGIN_CHECK_PATH, timeout: float = 8.0
) -> dict:
    """调用 get_qrcode_status 查询扫码状态；命中 token 时返回。

    注意：该接口是**长轮询**（带 ticket 时服务端会挂住，直到扫码状态变化或自身超时）。
    因此读超时属正常现象，返回 {}（表示"本次无变化"），由上层继续轮询；绝不能当错误。
    """
    url = normalize_url(api_url or FIXED_API_URL, check_path)
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}qrcode={quote(str(ticket))}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url, headers={"iLink-App-ClientVersion": "1"})
        if r.status_code >= 400:
            return {}
        return extract_login_payload(r.json())
    except httpx.TimeoutException:
        return {}   # 长轮询超时 = 无变化
    except Exception:  # noqa: BLE001
        return {}


def upsert_account(cfg: dict, *, token: str, api_url: str, bot_id: str = "",
                   account_name: str = "", x_wechat_uin: str = "") -> dict:
    """把扫码得到的 token 写入 accounts（去重：同 bot_id 或同 token 则更新）。"""
    token = str(token or "").strip()
    if not token:
        return cfg
    arr = cfg.get("accounts")
    if not isinstance(arr, list):
        arr = []
    if not account_name:
        account_name = f"wx_{len(arr) + 1}"
    bot_id = str(bot_id or "").strip()
    updated = False
    for row in arr:
        if not isinstance(row, dict):
            continue
        same_id = bot_id and str(row.get("bot_id") or row.get("myuid") or "").strip() == bot_id
        same_token = str(row.get("token") or "").strip() == token
        if same_id or same_token:
            row.update({"name": account_name, "bot_id": bot_id, "myuid": bot_id,
                        "token": token, "api_url": FIXED_API_URL, "x_wechat_uin": x_wechat_uin, "enabled": True})
            updated = True
            break
    if not updated:
        arr.append({"name": account_name, "bot_id": bot_id, "myuid": bot_id, "token": token,
                    "api_url": FIXED_API_URL, "x_wechat_uin": x_wechat_uin, "enabled": True})
    cfg["accounts"] = arr
    cfg["token"] = token  # 兼容单账号
    cfg["api_url"] = FIXED_API_URL
    return cfg
