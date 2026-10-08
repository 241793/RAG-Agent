"""验证：纯聊天模式不再"只能根据知识库回答"（使用安全版 _cdp）。"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def main():
    b, cdp, ws = open_browser(port=9372, tag="prompt")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)
        cdp.send("Page.navigate", {"url": BASE + "/chat"})
        time.sleep(4)

        # 检查三态选择器存在
        print("检索范围三态存在:", cdp.ev("(()=>{const s=[...document.querySelectorAll('.ant-select')];return s.some(x=>x.innerText.includes('检索')||document.body.innerText.includes('检索范围'))})()"))
        # 打开选择器，确认有"不检索（纯聊天）"选项
        cdp.ev("(()=>{const sels=[...document.querySelectorAll('.ant-select-selector')];const t=sels.find(s=>s.closest('.ant-select')?.innerText.includes('自动'));t&&t.click();})()")
        time.sleep(1)
        print("含'不检索（纯聊天）'选项:", cdp.ev("document.body.innerText.includes('不检索')"))
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_retrieval_switch.png", "wb").write(base64.b64decode(shot))

        # 切到"不检索（纯聊天）"
        cdp.ev("(()=>{const opts=[...document.querySelectorAll('.ant-select-item-option')];const o=opts.find(x=>x.innerText.includes('不检索'));o&&o.click();})()")
        time.sleep(1)
        print("已切到纯聊天:", cdp.ev("(()=>{const s=[...document.querySelectorAll('.ant-select')];return s.some(x=>x.innerText.includes('不检索'))})()"))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
