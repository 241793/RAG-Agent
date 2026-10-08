"""对话附件渲染验证：上传图片+文档 → 发送 → 检查渲染（图片内嵌、文档卡片）。"""
from __future__ import annotations

import base64
import os
import struct
import sys
import time
import zlib

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def _png():
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff\x00\x00"))
            + chunk(b"IEND", b""))


def main():
    tok = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
    h = {"Authorization": "Bearer " + tok}
    # 上传图片 + 文档（不带 kb_id，供对话展示）
    img = httpx.post(BASE + "/api/v1/chat/attachments?kind=image", headers=h,
                     files={"file": ("red.png", _png(), "image/png")}, timeout=10).json()
    doc = httpx.post(BASE + "/api/v1/chat/attachments?kind=document", headers=h,
                     files={"file": ("report.md", b"# Report\n\nhello world", "text/markdown")}, timeout=10).json()
    print("uploaded:", img["name"], doc["name"])

    b, cdp, ws = open_browser(port=9371, tag="att2")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)
        cdp.send("Page.navigate", {"url": BASE + "/chat"})
        time.sleep(4)

        # 直接把待发附件塞进 React：通过上传控件较难自动化，改为直接调用 send 逻辑——
        # 这里用更稳的方式：构造一条本地消息不可行，故改用 API 发消息后刷新会话查看渲染。
        # 先创建一个会话并通过 completions 带上附件（后端落库 attachments）
        conv = httpx.post(BASE + "/api/v1/chat/conversations", headers=h, json={"kb_ids": []}, timeout=10).json()
        cid = conv["id"]
        # 用 streamChat 的 HTTP 端点发送（带附件）
        payload = {"conversation_id": cid, "kb_ids": [], "message": "看看这两个附件", "stream": False,
                   "attachments": [img, doc]}
        # 非流式走 /chat/completions（stream=False）
        r = httpx.post(BASE + "/api/v1/chat/completions", headers=h, json=payload, timeout=60)
        print("completions:", r.status_code)

        # 前端打开该会话，检查附件渲染
        cdp.send("Page.navigate", {"url": f"{BASE}/chat?conv={cid}"})
        time.sleep(5)
        print("图片已内嵌(存在 img.ant-image-img):", cdp.ev("document.querySelectorAll('.ant-image-img, img').length > 0"))
        print("文档卡片存在(md 文件):", cdp.ev("document.body.innerText.includes('report.md')"))
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_attach_in_chat.png", "wb").write(base64.b64decode(shot))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
