"""聊天快捷定位 + 思考块 UI 验证（安全版 _cdp）。"""
from __future__ import annotations

import base64
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _cdp import open_browser  # noqa: E402

BASE = "http://127.0.0.1:6677"


def main():
    tok = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
    h = {"Authorization": "Bearer " + tok}
    convs = httpx.get(BASE + "/api/v1/chat/conversations", headers=h, timeout=10).json()
    # 找一个消息多的会话
    target = None
    for c in convs:
        ms = httpx.get(BASE + f"/api/v1/chat/conversations/{c['id']}/messages", headers=h, timeout=10).json()
        if len(ms) >= 4:
            target = c
            break
    cid = target["id"] if target else (convs[0]["id"] if convs else None)
    print("目标会话:", cid, target["title"] if target else "")

    b, cdp, ws = open_browser(port=9390, tag="nav")
    try:
        cdp.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(3)
        cdp.ev("(async()=>{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})});const d=await r.json();localStorage.setItem('access_token',d.access_token);return 'ok';})()", True)
        cdp.send("Page.navigate", {"url": BASE + "/chat"})
        time.sleep(4)
        if cid:
            cdp.ev(f"(()=>{{const its=[...document.querySelectorAll('.ant-list-item')];const it=its.find(x=>x.innerText.includes('{ (target['title'] if target else '')[:8] }'));it&&it.click();}})()")
            time.sleep(2)
        print("目录按钮存在:", cdp.ev("Array.from(document.querySelectorAll('button')).some(b=>b.innerText.includes('目录'))"))
        print("消息锚点存在:", cdp.ev("document.querySelectorAll('[id^=msg-]').length"))
        # 打开目录
        cdp.ev("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.includes('目录'))?.click()")
        time.sleep(1)
        print("目录抽屉打开:", cdp.ev("document.body.innerText.includes('对话目录')"))
        shot = cdp.send("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if shot:
            open("data/ui_outline.png", "wb").write(base64.b64decode(shot))
        # 关闭抽屉，测试向上翻 → 回到最新
        cdp.ev("document.querySelector('.ant-drawer-close')?.click()")
        time.sleep(0.5)
        cdp.ev("(()=>{const el=document.querySelector('[id^=msg-]')?.parentElement;return 'ok';})()")
        # 手动滚动到顶部
        cdp.ev("(()=>{const els=[...document.querySelectorAll('div')].filter(d=>d.scrollHeight>d.clientHeight+50 && d.querySelector('[id^=msg-]'));const el=els[els.length-1];if(el)el.scrollTop=0;return el?el.scrollTop:0;})()")
        time.sleep(1)
        print("向上翻后出现'回到最新':", cdp.ev("Array.from(document.querySelectorAll('button')).some(b=>b.innerText.includes('回到最新'))"))
        print("完成")
    finally:
        ws.close()
        b.stop()


if __name__ == "__main__":
    main()
